"""Subscription backend: `codex exec` subprocess on the economy model (spec 8.1, spike phase0).

The runner is injectable so tests never spawn codex.
Runner contract: runner(cmd, *, stdin, env, timeout_s, cwd) -> stdout text; raises TimeoutError on timeout.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile

from .decision import LEVELS, RISK_FLAGS, DifficultyDecision, DifficultyInput

GUARD_ENV = "MER_CLASSIFIER"  # child env guard: the Router's own hook must no-op when set
MAX_TASK_CHARS = 4000
MAX_PATHS = 50
LEVEL_DESCRIPTIONS = (  # shared with the Jev backend's score criteria
    "mechanical (rename, typo, trivial config)",
    "local change (single function, small bug fix)",
    "multi-file, moderate design judgment",
    "architectural (structure, persistence, concurrency design, API contract)",
    "critical/deep (security core, data-loss migration, complex concurrency, unknown root cause)",
)
DEFAULT_MODEL = "gpt-6-luna"  # default to confirm
CLAUDE_MODEL = "claude-haiku-4-5"  # the classifier model under host claude (plan Phase 5)


class BackendOutputError(ValueError):
    """Backend output could not be turned into a DifficultyDecision."""


def default_runner(cmd, *, stdin, env, timeout_s, cwd, label="classifier", grace_s=1):  # hook budget: short grace
    """Runs `cmd` in its own process group. On timeout or any interruption the group gets SIGTERM, then SIGKILL
    after `grace_s`, so a child that cleans up its own children on SIGTERM (mer) gets the chance to."""
    proc = subprocess.Popen(
        cmd, stdin=stdin, env=env, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True,  # own process group so a timeout can kill grandchildren
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"{label} exceeded {timeout_s}s") from exc
    finally:  # timeout, KeyboardInterrupt, anything: never leave the group running
        if proc.poll() is None:
            _stop_group(proc, grace_s)
    if proc.returncode != 0:
        raise RuntimeError(f"{label} exited {proc.returncode}: {stderr[-200:]}")
    return stdout


def _stop_group(proc, grace_s):
    """SIGTERM, wait for the leader up to `grace_s`, then SIGKILL whatever is left of the group."""
    for sig, wait_s in ((signal.SIGTERM, grace_s), (signal.SIGKILL, 5)):
        try:
            os.killpg(proc.pid, sig)
        except OSError:
            pass  # group already gone
        try:
            proc.communicate(timeout=wait_s)
        except (subprocess.TimeoutExpired, OSError):
            pass


def build_prompt(task: DifficultyInput) -> str:
    paths = "\n".join(task.paths[:MAX_PATHS]) or "(none)"
    return (
        "Classify the difficulty of this software task as one of:\n"
        + "".join(f"{lv} {d}\n" for lv, d in zip(LEVELS, LEVEL_DESCRIPTIONS)) +
        'Reply with ONLY a JSON object: {"level": "L1".."L5", "confidence": 0..1, '
        '"reason_codes": [short_snake_case], "risk_flags": subset of '
        '[security, auth, payment, data_migration, data_loss, concurrency]}.\n'
        "Do not run commands or edit files.\n\n"
        f"Task:\n{task.task[:MAX_TASK_CHARS]}\n\nChanged/expected paths:\n{paths}\n\n"
        f"Repo summary:\n{task.repo_summary[:MAX_TASK_CHARS] or '(none)'}\n"
    )


def _agent_text(stdout: str) -> str:
    """Last agent message in the `codex exec --json` stream; error events and non-JSON lines skipped."""
    text = None
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict) or ev.get("type") != "item.completed":
            continue
        item = ev.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message" and isinstance(item.get("text"), str):
            text = item["text"]
    if text is None:
        raise BackendOutputError("no agent message in classifier output")
    return text


def parse_usage(stdout: str):
    """Token usage of the last `turn.completed` event in the exec stream, or None if absent."""
    usage = None
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("type") == "turn.completed" and isinstance(ev.get("usage"), dict):
            usage = ev["usage"]
    return usage


def _as_list(value):
    """Only real lists count; a string is an invalid field, not a sequence of characters."""
    return value if isinstance(value, list) else []


def parse_output(stdout: str, backend_name: str) -> DifficultyDecision:
    return decision_from_text(_agent_text(stdout), backend_name)


def decision_from_text(text: str, backend_name: str) -> DifficultyDecision:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        data = json.loads(match.group(0)) if match else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise BackendOutputError("agent message is not a JSON object")
    # DifficultyDecision validates level / confidence; ValueError -> fallback applies.
    return DifficultyDecision(
        level=data.get("level"),
        backend=backend_name,
        confidence=data.get("confidence"),
        reason_codes=tuple(c for c in _as_list(data.get("reason_codes")) if isinstance(c, str)),
        risk_flags=tuple(f for f in _as_list(data.get("risk_flags")) if f in RISK_FLAGS),
    )


class SubscriptionBackend:
    name = "subscription"
    calls_model = True  # route events log its usage (explicit null when unreported)

    def __init__(self, runner=default_runner, model=None, host=None):
        self._runner = runner
        self._host = host  # "claude" or codex (None): given by the caller; the env is only read in host/hosts.get
        self._model = model
        self.last_usage = None  # usage of the most recent call, for evaluation (not part of DifficultyDecision)

    def classify(self, task: DifficultyInput, timeout_s: float) -> DifficultyDecision:
        self.last_usage = None  # never report a previous call's usage
        if self._host not in (None, "codex", "claude"):
            raise ValueError(f"subscription classifier is not supported for {self._host}: tool isolation is unverified")
        if self._host == "claude":
            return self._classify_claude(task, timeout_s)
        cmd = [
            "codex", "exec", "--json", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config",
            "-s", "read-only",
            "-m", self._model or DEFAULT_MODEL, "-c", "model_reasoning_effort=low",
            build_prompt(task),
        ]
        env = {**os.environ, GUARD_ENV: "1"}
        # Empty per-call dir: no repo files and no .codex/ hooks/agents for the nested exec to load.
        cwd = tempfile.mkdtemp(prefix="mer-classifier-")
        try:
            stdout = self._runner(cmd, stdin=subprocess.DEVNULL, env=env, timeout_s=timeout_s, cwd=cwd)
        finally:
            shutil.rmtree(cwd, ignore_errors=True)
        self.last_usage = parse_usage(stdout)
        return parse_output(stdout, self.name)

    def _classify_claude(self, task, timeout_s):
        """`claude -p` on Haiku, as isolated and cheap as --help allows: no tools (`--tools ""`), safe mode (no CLAUDE.md,
        skills, plugins, hooks, MCP, memory), no MCP servers, nothing persisted, an empty cwd, guard env set."""
        from ..host import claude_exec  # lazy: claude_exec imports this module
        cmd = ["claude", "-p", "--output-format", "json", "--model", self._model or CLAUDE_MODEL,
               "--permission-mode", "dontAsk", "--tools", "", "--safe-mode", "--strict-mcp-config", "--no-session-persistence",
               "--", build_prompt(task)]
        env = {**os.environ, GUARD_ENV: "1"}
        cwd = tempfile.mkdtemp(prefix="mer-classifier-")
        try:
            stdout = self._runner(cmd, stdin=subprocess.DEVNULL, env=env, timeout_s=timeout_s, cwd=cwd)
        finally:
            shutil.rmtree(cwd, ignore_errors=True)
        try:
            stream = claude_exec.parse_stream(stdout)
        except claude_exec.ClaudeResultError as exc:
            raise BackendOutputError(str(exc)) from exc
        u = stream.usage  # back to the codex-style keys every classifier-usage consumer reads
        self.last_usage = {"input_tokens": u["input"], "cached_input_tokens": u["cached_input"],
                           "output_tokens": u["output"], "reasoning_output_tokens": 0}
        return decision_from_text(stream.text, self.name)

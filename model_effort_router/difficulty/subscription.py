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
from dataclasses import replace

from .decision import DifficultyDecision, DifficultyInput, EFFORTS, ROLES
from ..events import iter_events

GUARD_ENV = "MER_CLASSIFIER"  # child env guard: the Router's own hook must no-op when set
MAX_TASK_CHARS = 4000
MAX_PATHS = 50
DEFAULT_MODEL = "gpt-6-luna"  # default to confirm
CLAUDE_MODEL = "claude-haiku-4-5"  # the classifier model under host claude (plan Phase 5)


class BackendOutputError(ValueError):
    """Backend output could not be turned into a DifficultyDecision."""


class CliAuthError(RuntimeError):
    """The host CLI is not signed in (or its sign-in expired): a fix for the user, not a retry."""


AUTH_FAILURE = re.compile(r"failed to authenticate|not logged in|unauthori[sz]ed|\b401\b", re.I)


def _failure_detail(stdout, stderr):
    """Why a child failed: stderr, else the result/subtype of a JSON stdout (claude -p reports errors there).
    Other stdout is not echoed: codex streams events that can hold file contents."""
    if stderr.strip():
        return stderr[-200:]
    try:
        data = json.loads(stdout)
    except ValueError:
        data = None
    text = (data.get("result") or data.get("subtype")) if isinstance(data, dict) else None
    return text[:200] if isinstance(text, str) and text else "(no stderr)"


def default_runner(cmd, *, stdin, env, timeout_s, cwd, label="classifier", grace_s=1, input_text=None):  # hook budget: short grace
    """Runs `cmd` in its own process group. On timeout or any interruption the group gets SIGTERM, then SIGKILL
    after `grace_s`, so a child that cleans up its own children on SIGTERM (mer) gets the chance to.
    `input_text` is written to the child's stdin (instead of `stdin`), keeping large or private text out of argv."""
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE if input_text is not None else stdin, env=env, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True,  # own process group so a timeout can kill grandchildren
    )
    try:
        stdout, stderr = proc.communicate(input=input_text, timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"{label} exceeded {timeout_s}s") from exc
    finally:  # timeout, KeyboardInterrupt, anything: never leave the group running
        if proc.poll() is None:
            _stop_group(proc, grace_s)
    if proc.returncode != 0:
        detail = _failure_detail(stdout, stderr)
        raise (CliAuthError if AUTH_FAILURE.search(detail) else RuntimeError)(f"{label} exited {proc.returncode}: {detail}")
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


def isolated_argv(host, prompt, model=None):  # prompt=None: the caller feeds it on stdin (`claude -p`, `codex exec -`)
    """One-shot, tool-less model call through the host's subscription CLI. Claude: `claude -p`, as isolated and cheap as
    --help allows: no tools (`--tools ""`), safe mode (no CLAUDE.md, skills, plugins, hooks, MCP, memory), no MCP servers,
    nothing persisted. Codex: `codex exec` read-only, ephemeral, user config ignored."""
    if host == "claude":
        return ["claude", "-p", "--output-format", "json", "--model", model or CLAUDE_MODEL,
                "--permission-mode", "dontAsk", "--tools", "", "--safe-mode", "--strict-mcp-config", "--no-session-persistence",
                *(["--", prompt] if prompt is not None else [])]
    return ["codex", "exec", "--json", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config", "-s", "read-only",
            "-m", model or DEFAULT_MODEL, "-c", "model_reasoning_effort=low", "-" if prompt is None else prompt]  # "-": stdin


def run_isolated(argv, runner, timeout_s, input_text=None):
    """Runs `argv` with the guard env set (the nested CLI's own hook must no-op) in an empty per-call dir: no repo files
    and no .codex/ or .claude/ hooks/agents for the child to load."""
    env = {**os.environ, GUARD_ENV: "1"}
    cwd = tempfile.mkdtemp(prefix="mer-classifier-")
    try:
        extra = {} if input_text is None else {"input_text": input_text}
        return runner(argv, stdin=subprocess.DEVNULL, env=env, timeout_s=timeout_s, cwd=cwd, **extra)
    finally:
        shutil.rmtree(cwd, ignore_errors=True)


def build_prompt(task: DifficultyInput) -> str:
    paths = "\n".join(task.paths[:MAX_PATHS]) or "(none)"
    context = f"Session context (earlier conversation; use it only to interpret the task):\n{task.context}\n\n" if task.context else ""
    return (
        "Classify the requested work. Role must be one of " + ", ".join(ROLES) + ". Effort must be one of "
        + ", ".join(EFFORTS) + ".\n"
        'Reply with ONLY JSON: {"role":"implementation","effort":"medium","confidence":0.8, '
        '"reason_code":"short_snake_case"}. Only role and effort are required.\n'
        "Do not run commands or edit files.\n\n"
        f"{context}Task:\n{task.task[:MAX_TASK_CHARS]}\n\nChanged/expected paths:\n{paths}\n\n"
        f"Repo summary:\n{task.repo_summary[:MAX_TASK_CHARS] or '(none)'}\n"
    )


def _agent_text(stdout: str) -> str:
    """Last agent message in the `codex exec --json` stream; error events and non-JSON lines skipped."""
    text = None
    for ev in iter_events(stdout):
        if ev.get("type") != "item.completed":
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
    for ev in iter_events(stdout):
        if ev.get("type") == "turn.completed" and isinstance(ev.get("usage"), dict):
            usage = ev["usage"]
    return usage


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
    from .jev import parse_decision
    return parse_decision(data, backend_name)


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
        # A read-only agent that still has a shell: transcript text must not reach it (prompt injection), so no context.
        prompt = build_prompt(replace(task, context=""))
        stdout = run_isolated(isolated_argv("codex", None, self._model), self._runner, timeout_s, input_text=prompt)
        self.last_usage = parse_usage(stdout)
        return parse_output(stdout, self.name)

    def _classify_claude(self, task, timeout_s):
        """`claude -p` on Haiku with the isolation of `isolated_argv`."""
        from ..host import claude_exec  # lazy: claude_exec imports this module
        stdout = run_isolated(isolated_argv("claude", None, self._model), self._runner, timeout_s, input_text=build_prompt(task))
        try:
            stream = claude_exec.parse_stream(stdout)
        except claude_exec.ClaudeResultError as exc:
            raise BackendOutputError(str(exc)) from exc
        u = stream.usage  # back to the codex-style keys every classifier-usage consumer reads
        self.last_usage = {"input_tokens": u["input"], "cached_input_tokens": u["cached_input"],
                           "output_tokens": u["output"], "reasoning_output_tokens": 0}
        return decision_from_text(stream.text, self.name)

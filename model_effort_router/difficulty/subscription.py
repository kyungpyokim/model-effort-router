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

from .decision import RISK_FLAGS, DifficultyDecision, DifficultyInput

GUARD_ENV = "MER_CLASSIFIER"  # child env guard: the Router's own hook must no-op when set
MAX_TASK_CHARS = 4000
MAX_PATHS = 50
DEFAULT_MODEL = "gpt-6-luna"  # default to confirm


class BackendOutputError(ValueError):
    """Backend output could not be turned into a DifficultyDecision."""


def default_runner(cmd, *, stdin, env, timeout_s, cwd):
    proc = subprocess.Popen(
        cmd, stdin=stdin, env=env, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True,  # own process group so a timeout can kill grandchildren
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"classifier exceeded {timeout_s}s") from exc
    finally:  # timeout, KeyboardInterrupt, anything: never leave the group running
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            try:
                proc.communicate(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                pass
    if proc.returncode != 0:
        raise RuntimeError(f"classifier exited {proc.returncode}: {stderr[-200:]}")
    return stdout


def build_prompt(task: DifficultyInput) -> str:
    paths = "\n".join(task.paths[:MAX_PATHS]) or "(none)"
    return (
        "Classify the difficulty of this software task as one of:\n"
        "L1 mechanical (rename, typo, trivial config)\n"
        "L2 local change (single function, small bug fix)\n"
        "L3 multi-file, moderate design judgment\n"
        "L4 architectural (structure, persistence, concurrency design, API contract)\n"
        "L5 critical/deep (security core, data-loss migration, complex concurrency, unknown root cause)\n"
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
    text = _agent_text(stdout)
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

    def __init__(self, runner=default_runner, model=DEFAULT_MODEL):
        self._runner = runner
        self._model = model
        self.last_usage = None  # usage of the most recent call, for evaluation (not part of DifficultyDecision)

    def classify(self, task: DifficultyInput, timeout_s: float) -> DifficultyDecision:
        self.last_usage = None  # never report a previous call's usage
        cmd = [
            "codex", "exec", "--json", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config",
            "-s", "read-only",
            "-m", self._model, "-c", "model_reasoning_effort=low",
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

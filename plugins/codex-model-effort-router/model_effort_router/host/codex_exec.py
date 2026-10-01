"""`codex exec` command lines and `--json` stream parsing for mer-driven sessions (spec 3.4)."""
import json
import subprocess
from collections import namedtuple

from ..adapters.codex import CodexConfig, resolve
from ..difficulty.subscription import GUARD_ENV, default_runner

KEYS = {"input_tokens": "input", "cached_input_tokens": "cached_input",
        "output_tokens": "output", "reasoning_output_tokens": "reasoning_output"}
Stream = namedtuple("Stream", "thread_id usage text")  # usage: cumulative for the thread, short keys, or None


def _base(verb, resolved, sandbox):
    cmd = ["codex", "exec"] + verb + ["--json", "--skip-git-repo-check"]
    if sandbox:
        cmd += ["-s", sandbox]
    return cmd + ["-m", resolved.model, "-c", f"model_reasoning_effort={resolved.applied_effort}"]


def session_argv(profile, prompt, sandbox, config=CodexConfig()):
    return _base([], resolve(profile, config), sandbox) + [prompt]


def resume_argv(profile, thread_id, prompt, config=CodexConfig()):
    """`exec resume` has no -s flag; set the sandbox via config so escalated rungs can still edit files."""
    cmd = _base(["resume"], resolve(profile, config), None)
    return cmd + ["-c", 'sandbox_mode="workspace-write"', thread_id, prompt]


def session_env(base):
    return {**base, GUARD_ENV: "1"}  # the installed plugin's hooks no-op inside mer-driven sessions


def run_subprocess(argv, *, cwd, env, timeout_s):
    return default_runner(argv, stdin=subprocess.DEVNULL, env=env, timeout_s=timeout_s, cwd=cwd, label="codex exec")


def _events(text):
    for line in text.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict):
            yield ev


def parse_stream(text) -> Stream:
    """Thread id, last agent message and the last (cumulative) `turn.completed` usage of one exec stream."""
    thread_id, usage, message = None, None, None
    for ev in _events(text):
        kind = ev.get("type")
        item = ev.get("item")
        if kind == "thread.started":
            thread_id = ev.get("thread_id")
        elif kind == "turn.completed" and isinstance(ev.get("usage"), dict):
            usage = {short: int(ev["usage"].get(long) or 0) for long, short in KEYS.items()}
        elif kind == "item.completed" and isinstance(item, dict) and item.get("type") == "agent_message":
            message = item.get("text") if isinstance(item.get("text"), str) else message
    return Stream(thread_id, usage, message)


class UsageTracker:
    """`turn.completed.usage` is cumulative per thread (resume included): per-call usage is the difference."""

    def __init__(self):
        self._seen = {}

    def delta(self, thread_id, cumulative):
        if cumulative is None:
            return None
        prev = self._seen.get(thread_id, dict.fromkeys(cumulative, 0))
        self._seen[thread_id] = {k: max(prev[k], v) for k, v in cumulative.items()}
        return {k: max(0, v - prev[k]) for k, v in cumulative.items()}

"""`codex exec` command lines and `--json` stream parsing for mer-driven sessions (spec 3.4)."""
import subprocess
from collections import namedtuple

from ..adapters.codex import CodexConfig, resolve
from ..adapters.common import ResolvedProfile
from ..difficulty.subscription import default_runner
from . import session_env as session_env
from ..events import iter_events as _events

KEYS = {"input_tokens": "input", "cached_input_tokens": "cached_input",
        "output_tokens": "output", "reasoning_output_tokens": "reasoning_output"}
Stream = namedtuple("Stream", "thread_id usage text")  # usage: cumulative for the thread, short keys, or None


def agents_flags(subagents):
    """Per-call `-c` overrides only (never user config): 0 = no subagents, n >= 1 = at most n concurrent, None = default."""
    if subagents is None:
        return []
    if subagents == 0:
        return ["-c", "agents.enabled=false"]
    return ["-c", "agents.enabled=true", "-c", f"agents.max_concurrent_threads_per_session={subagents}"]


def _base(verb, resolved, sandbox, subagents=None):
    cmd = ["codex", "exec"] + verb + ["--json", "--skip-git-repo-check"]
    if sandbox:
        cmd += ["-s", sandbox]
    return cmd + ["-m", resolved.model, "-c", f"model_reasoning_effort={resolved.applied_effort}"] + agents_flags(subagents)


def session_argv(profile, prompt, sandbox, config=CodexConfig(), subagents=None):
    resolved = profile if isinstance(profile, ResolvedProfile) else resolve(profile, config)
    return _base([], resolved, sandbox, subagents) + [prompt]


def resume_argv(profile, thread_id, prompt, config=CodexConfig(), subagents=None):
    """`exec resume` has no -s flag; set the sandbox through host config."""
    cmd = _base(["resume"], resolve(profile, config), None, subagents)
    return cmd + ["-c", 'sandbox_mode="workspace-write"', thread_id, prompt]


def run_subprocess(argv, *, cwd, env, timeout_s):
    return default_runner(argv, stdin=subprocess.DEVNULL, env=env, timeout_s=timeout_s, cwd=cwd, label="codex exec",
                          grace_s=5)


def parse_stream(text) -> Stream:
    """Thread id, last agent message and the last (cumulative) `turn.completed` usage of one exec stream."""
    thread_id, usage, message, completed = None, None, None, False
    for ev in _events(text):
        kind = ev.get("type")
        item = ev.get("item")
        if kind == "thread.started":
            thread_id = ev.get("thread_id")
        elif kind == "turn.completed" and isinstance(ev.get("usage"), dict):
            usage = {short: int(ev["usage"].get(long) or 0) for long, short in KEYS.items()}
        elif kind == "turn.completed":
            completed = True
        elif kind == "item.completed" and isinstance(item, dict) and item.get("type") == "agent_message":
            message = item.get("text") if isinstance(item.get("text"), str) else message
        if kind == "turn.completed":
            completed = True
    if not completed:
        raise ValueError("codex stream ended without turn.completed")
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

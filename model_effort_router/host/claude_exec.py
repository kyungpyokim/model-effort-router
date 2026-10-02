"""`claude -p` command lines and `--output-format json` result parsing for mer-driven sessions (plan Phase 5).

Counterpart of host/codex_exec.py with the same function names, so flow.py stays host-agnostic.
Everything about Claude Code's runtime behaviour here is from `claude --help` (CLI 2.1.280) and the documented
result shape; it is UNVERIFIED live, so parsing fails closed like difficulty/jev.py.
"""
import json
import subprocess
from collections import namedtuple

from ..adapters.claude import ClaudeConfig, resolve
from ..difficulty.subscription import GUARD_ENV, default_runner

Stream = namedtuple("Stream", "thread_id usage text extra", defaults=(None,))  # usage: THIS invocation's, short keys, or None
READ_ONLY_TOOLS = "Read,Grep,Glob"


class ClaudeResultError(ValueError):
    """The result is not the documented success shape (or Claude Code reported an error)."""


def agents_flags(subagents):
    """0 = Agent tool denied. n >= 1: Claude Code has no concurrency cap, so Agent stays allowed (the prompt hint
    carries the limit). None = default."""
    return ["--disallowedTools", "Agent"] if subagents == 0 else []


def _base(resolved, extra):
    cmd = ["claude", "-p", "--output-format", "json", "--model", resolved.model]
    if resolved.applied_effort:  # a model without supported efforts (Haiku) takes no --effort
        cmd += ["--effort", resolved.applied_effort]
    return cmd + extra


def _prompted(cmd, prompt):
    return cmd + ["--", prompt]  # --allowedTools/--disallowedTools are variadic: `--` keeps the prompt out of them


def session_argv(profile, prompt, sandbox, config=ClaudeConfig(), subagents=None):
    """sandbox "workspace-write" = an implement session (permission mode auto); anything else is read-only:
    dontAsk with Read/Grep/Glob only and the Agent tool always denied."""
    resolved = resolve(profile, config)
    if sandbox == "workspace-write":
        extra = ["--permission-mode", "auto"] + agents_flags(subagents)
    else:
        # --tools restricts the tool SET itself (--allowedTools only pre-approves: settings could still allow Edit/Bash);
        # project/local settings and MCP servers are left out so nothing else can grant a tool
        extra = ["--permission-mode", "dontAsk", "--tools", READ_ONLY_TOOLS, "--allowedTools", READ_ONLY_TOOLS,
                 "--disallowedTools", "Agent", "--strict-mcp-config", "--setting-sources", "user"]
    return _prompted(_base(resolved, extra), prompt)


def resume_argv(profile, session_id, prompt, config=ClaudeConfig(), subagents=None):
    extra = ["--permission-mode", "auto"] + agents_flags(subagents) + ["--resume", session_id]
    return _prompted(_base(resolve(profile, config), extra), prompt)


def session_env(base):
    return {**base, GUARD_ENV: "1"}  # the installed plugin's hook stays quiet inside mer-driven sessions


def run_subprocess(argv, *, cwd, env, timeout_s):
    return default_runner(argv, stdin=subprocess.DEVNULL, env=env, timeout_s=timeout_s, cwd=cwd, label="claude -p",
                          grace_s=5)


def _count(usage, key, required):
    v = usage.get(key)
    if v is None and not required:
        return 0
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        raise ClaudeResultError(f"usage.{key} is missing or not a count")
    return v


def parse_stream(text) -> Stream:
    """The single JSON result. An error result (is_error) or any other shape raises."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise ClaudeResultError("claude output is not one JSON object") from exc
    if not isinstance(data, dict) or data.get("type") != "result":
        raise ClaudeResultError("claude output is not a result object")
    if data.get("is_error") is not False:
        raise ClaudeResultError(f"claude reported an error result ({str(data.get('subtype'))[:60]})")
    sid, result, usage = data.get("session_id"), data.get("result"), data.get("usage")
    if not isinstance(sid, str) or not sid or not isinstance(result, str) or not isinstance(usage, dict):
        raise ClaudeResultError("claude result lacks session_id, result or usage")
    fresh, created, read = (_count(usage, "input_tokens", True), _count(usage, "cache_creation_input_tokens", False),
                            _count(usage, "cache_read_input_tokens", False))
    extra = {k: data[k] for k, ok in (("total_cost_usd", lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)),
                                     ("modelUsage", lambda v: isinstance(v, dict))) if k in data and ok(data[k])}
    return Stream(sid, {"input": fresh + created + read, "cached_input": read,
                        "output": _count(usage, "output_tokens", True), "reasoning_output": 0}, result, extra or None)


class UsageTracker:
    """Claude Code reports usage per invocation (resume included), unlike codex's cumulative stream: no subtraction."""

    def delta(self, thread_id, usage):
        return None if usage is None else dict(usage)

"""`claude -p` command lines and `--output-format json` result parsing for mer-driven sessions (plan Phase 5).

Counterpart of host/codex_exec.py with the same function names, so flow.py stays host-agnostic.
Everything about Claude Code's runtime behaviour here is from `claude --help` (CLI 2.1.280) and the documented
result shape; it is UNVERIFIED live, so parsing fails closed like difficulty/jev.py.

Fixed context (pilot-c1: ~200k tokens per session): a user's enabled plugins, user hooks (SessionStart injects large
text) and MCP tool lists ride along in every `claude -p`. "lean" (config.context, default) keeps CLAUDE.md memory
(project chain, ~/.claude/rules) but loads only project/local settings (`--setting-sources project,local`: enabledPlugins
and user hooks live in user settings) and no MCP servers (`--strict-mcp-config`). Not --safe-mode (drops CLAUDE.md) and
not --bare (needs an API key). "full" is the unrestricted argv. The classifier already runs --safe-mode in a temp dir.
Lean keeps the user's own guard rails (permissions.deny/ask, sandbox, PreToolUse/PermissionRequest hooks from the user
settings file) via `--settings`; plugin-provided guard hooks and other user settings are dropped.
Read-only sessions (review/plan) never load project or local settings, in either mode: a reviewed change could add
a `.claude/settings.local.json` whose hooks, apiKeyHelper, env or extra directories would otherwise run or redirect them.
"""
import json
import os
import subprocess
from collections import namedtuple

from ..adapters.claude import ClaudeConfig, resolve
from ..difficulty.subscription import GUARD_ENV, default_runner

Stream = namedtuple("Stream", "thread_id usage text extra", defaults=(None,))  # usage: THIS invocation's, short keys, or None
READ_ONLY_TOOLS = "Read,Grep,Glob"
GUARD_HOOK_EVENTS = ("PreToolUse", "PermissionRequest")  # the only user hooks lean sessions keep (SessionStart etc. inject context)


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


def user_guards(path=None, read=None):
    """The user's guard rails from their settings file: only permissions.deny/ask, sandbox and the PreToolUse and
    PermissionRequest hooks. A missing, unreadable or
    invalid file means nothing to pass (never an error). `read(path) -> text` is injectable for tests."""
    path = path or os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude"),
                                "settings.json")
    try:
        data = json.loads((read or (lambda p: open(p, encoding="utf-8").read()))(path))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    perms = data.get("permissions") if isinstance(data.get("permissions"), dict) else {}
    out = {k: perms[k] for k in ("deny", "ask") if isinstance(perms.get(k), list) and perms[k]}
    guards = {"permissions": out} if out else {}
    if data.get("sandbox"):
        guards["sandbox"] = data["sandbox"]
    hooks = data.get("hooks") if isinstance(data.get("hooks"), dict) else {}
    kept = {e: hooks[e] for e in GUARD_HOOK_EVENTS if isinstance(hooks.get(e), list) and hooks[e]}  # guard hooks only
    if kept:
        guards["hooks"] = kept
    return guards


def isolation(config, read_only):
    """Context flags. full: the unrestricted implement argv, and read-only sessions with user settings (as before).
    lean implement/resume: project,local settings, no MCP servers, plus the user's own deny/ask/sandbox and PreToolUse/PermissionRequest hooks.
    lean read-only: user settings only (never project/local) with all hooks disabled."""
    if config.context == "lean":
        if read_only:
            return ["--strict-mcp-config", "--setting-sources", "user", "--settings", '{"disableAllHooks": true}']
        guards = (config.guards or user_guards)()
        return ["--setting-sources", "project,local", "--strict-mcp-config",
                *(["--settings", json.dumps(guards, sort_keys=True, separators=(",", ":"))] if guards else [])]
    return ["--strict-mcp-config", "--setting-sources", "user"] if read_only else []


def _prompted(cmd, prompt):
    return cmd + ["--", prompt]  # --allowedTools/--disallowedTools are variadic: `--` keeps the prompt out of them


def session_argv(profile, prompt, sandbox, config=ClaudeConfig(), subagents=None):
    """sandbox "workspace-write" = an implement session (permission mode auto); anything else is read-only:
    dontAsk with Read/Grep/Glob only and the Agent tool always denied."""
    resolved = resolve(profile, config)
    if sandbox == "workspace-write":
        extra = ["--permission-mode", "auto"] + agents_flags(subagents) + isolation(config, False)
    else:
        # --tools restricts the tool SET itself (--allowedTools only pre-approves: settings could still allow Edit/Bash);
        # no MCP servers, and user settings only in full context, so nothing else can grant a tool
        extra = ["--permission-mode", "dontAsk", "--tools", READ_ONLY_TOOLS, "--allowedTools", READ_ONLY_TOOLS,
                 "--disallowedTools", "Agent"] + isolation(config, True)
    return _prompted(_base(resolved, extra), prompt)


def resume_argv(profile, session_id, prompt, config=ClaudeConfig(), subagents=None):
    extra = ["--permission-mode", "auto"] + agents_flags(subagents) + isolation(config, False) + ["--resume", session_id]
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
        # live 2026-10-03: an expired login comes back as subtype "success" with is_error and the reason in `result`
        reason = data.get("result") if isinstance(data.get("result"), str) else data.get("subtype")
        raise ClaudeResultError(f"claude reported an error result: {str(reason)[:160]}")
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

"""`claude -p` command lines and `--output-format json` result parsing for mer-driven sessions (plan Phase 5).

Counterpart of host/codex_exec.py with the same function names, so flow.py stays host-agnostic.
Everything about Claude Code's runtime behaviour here is from `claude --help` (CLI 2.1.280) and the documented
result shape; it is UNVERIFIED live, so parsing fails closed like difficulty/jev.py.

Fixed context (pilot-c1: ~200k tokens per session): the user's enabled plugins and MCP tool lists ride along in every
`claude -p`. "lean" (config.context, default) turns exactly those off and keeps everything else: all settings sources and
instructions (CLAUDE.md chain, ~/.claude/rules), the user's permissions and hooks. Plugins: `--settings` with
`enabledPlugins: {id: false}` for every plugin enabled in the user settings or the cwd's project/local settings (unverified
live that this overrides a user `true`). MCP: `--strict-mcp-config`. Not --safe-mode (drops CLAUDE.md), not --bare (needs an
API key), and not --setting-sources (a probe showed project,local dropped ~/.claude/rules). "full" is the unrestricted argv.
The classifier already runs --safe-mode in a temp dir.
Read-only sessions (review/plan) never load project or local settings, in either mode: a reviewed change could add
a `.claude/settings.local.json` whose hooks, apiKeyHelper, env or extra directories would otherwise run or redirect them;
lean also disables all their hooks.
"""
import json
import os
import subprocess
from collections import namedtuple

from ..adapters.claude import ClaudeConfig, resolve
from ..adapters.common import ResolvedProfile
from ..difficulty.subscription import default_runner
from . import session_env as session_env

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


def _user_settings_path():
    return os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude"), "settings.json")


def _settings(cwd=None, read=None):
    """Parsed settings dicts in precedence order (user, then cwd/.claude/settings.json, then settings.local.json).
    A missing, unreadable or invalid file is skipped (never an error). `read(path) -> text` is injectable."""
    read = read or _read_settings
    paths = [_user_settings_path()] + ([os.path.join(cwd, ".claude", n) for n in ("settings.json", "settings.local.json")] if cwd else [])
    out = []
    for path in paths:
        try:
            data = json.loads(read(path))
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(data, dict):
            out.append(data)
    return out


def _read_settings(path):
    with open(path, encoding="utf-8") as stream:
        return stream.read()


def plugins_off(cwd=None, read=None):
    """{plugin id: False} for every plugin enabled (true) in the user settings and in `cwd`/.claude/settings(.local).json."""
    off = {}
    for data in _settings(cwd, read):
        enabled = data.get("enabledPlugins")
        if isinstance(enabled, dict):
            off.update({k: False for k, v in enabled.items() if v is True and isinstance(k, str)})
    return off


def default_session(cwd=None, read=None):
    """(model, effortLevel) Claude Code starts a session with, from the same settings files (later files win);
    None where unset. A /model or /effort switch inside the running session is not visible here."""
    model = effort = None
    for data in _settings(cwd, read):
        model = data["model"] if isinstance(data.get("model"), str) else model
        effort = data["effortLevel"] if isinstance(data.get("effortLevel"), str) else effort
    return model, effort


def isolation(config, read_only):
    """Context flags. full: the unrestricted implement argv, and read-only sessions with user settings (as before).
    lean implement/resume: all settings sources, no MCP servers, enabled plugins turned off.
    lean read-only: user settings only (never project/local) with all hooks disabled."""
    if config.context == "lean":
        if read_only:
            return ["--strict-mcp-config", "--setting-sources", "user", "--settings", '{"disableAllHooks": true}']
        off = (config.plugins_off or plugins_off)()
        return ["--strict-mcp-config",
                *(["--settings", json.dumps({"enabledPlugins": off}, sort_keys=True, separators=(",", ":"))] if off else [])]
    return ["--strict-mcp-config", "--setting-sources", "user"] if read_only else []


def _prompted(cmd, prompt):
    return cmd + ["--", prompt]  # --allowedTools/--disallowedTools are variadic: `--` keeps the prompt out of them


def session_argv(profile, prompt, sandbox, config=ClaudeConfig(), subagents=None):
    """sandbox "workspace-write" = an implement session (permission mode auto); anything else is read-only:
    dontAsk with Read/Grep/Glob only and the Agent tool always denied."""
    resolved = profile if isinstance(profile, ResolvedProfile) else resolve(profile, config)
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
    resolved = profile if isinstance(profile, ResolvedProfile) else resolve(profile, config)
    return _prompted(_base(resolved, extra), prompt)


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

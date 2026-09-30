"""Codex Host Hook Adapter: stdin JSON -> Router Core -> stdout JSON. Every handler fails open (spec 3.7, spike)."""
import importlib
import json
import os
import sys
import time
from pathlib import Path

from ..difficulty.registry import BACKENDS
from ..difficulty.subscription import GUARD_ENV
from ..logging import route_log
from ..policy.config import resolve_config
from ..policy.router import route
from ..policy.targeting import NO_ROUTE
from . import instructions, state as host_state

REGISTRY_MODULE_ENV = "MER_TEST_REGISTRY_MODULE"  # tests only: a module under tests/ with register(registry, env)
USER_CONFIG_ENV = "MER_USER_CONFIG"
REPO_CONFIG = ".model-effort-router.json"
MAX_BACKEND_TIMEOUT_S = 12  # backend + fallback must fit in the 30s hook timeout with margin


def _registry(env):
    reg = dict(BACKENDS)
    module = env.get(REGISTRY_MODULE_ENV)
    if module:
        if not module.startswith("tests."):
            raise ValueError("test registry module must live under tests/")
        importlib.import_module(module).register(reg, env)
    return reg


def _load_json(path):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def load_configs(cwd, env):
    """(repo, user) config dicts. User config: $MER_USER_CONFIG or ~/.config/model-effort-router/config.json."""
    home = env.get("HOME") or os.path.expanduser("~")
    user_path = env.get(USER_CONFIG_ENV) or os.path.join(
        env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"), "model-effort-router", "config.json")
    return _load_json(Path(cwd) / REPO_CONFIG), _load_json(user_path)


def _context_output(event, text):
    return json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}})


def _with_timeout(repo_cfg, timeout_s):
    repo_cfg = repo_cfg or {}
    return {**repo_cfg, "difficulty": {**repo_cfg.get("difficulty", {}), "timeout_s": timeout_s}}


def _safely(env, data, event, fn):
    """Persistence and logging must never change what the hook decides."""
    try:
        fn()
    except Exception as exc:
        _log_error(env, data, exc, event)


def _age_out_plan(sdir, sid):
    with host_state.locked(sdir, sid):
        state = host_state.load(sdir, sid)
        if state is None:
            return
        action, new = host_state.after_no_route(state, time.time())
        if action == "drop":
            host_state.delete(sdir, sid)
        else:
            host_state.save(sdir, sid, new)


def user_prompt_submit(data, env, plugin_root):
    prompt = data.get("prompt")
    if not isinstance(prompt, str):
        return None
    sid = data["session_id"]
    sdir = host_state.state_dir(env)
    repo_cfg, user_cfg = load_configs(data.get("cwd") or os.getcwd(), env)
    registry = _registry(env)
    cfg = resolve_config(repo=repo_cfg, user=user_cfg, registry=registry)
    clamped = cfg.timeout_s > MAX_BACKEND_TIMEOUT_S
    if clamped:
        repo_cfg = _with_timeout(repo_cfg, MAX_BACKEND_TIMEOUT_S)
    started = time.monotonic()
    plan = route(prompt, repo_config=repo_cfg, user_config=user_cfg, registry=registry)
    latency_ms = (time.monotonic() - started) * 1000
    if plan.target == NO_ROUTE:
        _safely(env, data, "UserPromptSubmit", lambda: _age_out_plan(sdir, sid))
        return _context_output("UserPromptSubmit", "[model-effort-router] The /router override line was not "
                               "understood and was ignored.") if plan.override_rejected else None

    gate_cmd = str(Path(plugin_root) / "bin" / "mer-gate")
    state = host_state.build_state(plan, session_id=sid, gate_cmd=gate_cmd)
    out = _context_output("UserPromptSubmit", instructions.render_from_state(state, rejected=plan.override_rejected))

    def persist():
        with host_state.locked(sdir, sid):
            host_state.save(sdir, sid, state)

    _safely(env, data, "UserPromptSubmit", persist)
    _safely(env, data, "UserPromptSubmit", lambda: route_log.append(sdir, sid, route_log.route_event(
        plan, state, latency_ms=latency_ms, prompt=prompt, configured_backend=cfg.backend,
        timeout_clamped=clamped)))
    return out


def _is_spawn(tool_name):
    return isinstance(tool_name, str) and tool_name.endswith("spawn_agent")  # observed: collaborationspawn_agent


def pre_tool_use(data, env, plugin_root):
    if not _is_spawn(data.get("tool_name")):
        return None
    sid, sdir = data["session_id"], host_state.state_dir(env)
    ti = data.get("tool_input")
    with host_state.locked(sdir, sid):
        state = host_state.load(sdir, sid)
        if state is None:
            return None
        decision, reason, stage, new_state = host_state.check_spawn(state, ti)
        if stage is None:
            return None
        if new_state is not state:
            _safely(env, data, "PreToolUse", lambda: host_state.save(sdir, sid, new_state))
    _safely(env, data, "PreToolUse", lambda: route_log.append(sdir, sid, {
        "event": "stage_spawn", "stage": stage, "decision": decision, "model": ti.get("model"),
        "effort": ti.get("reasoning_effort"), "fork_turns": ti.get("fork_turns"),
        "fix_count": new_state["fix_count"],
        **({"reason": reason} if reason else {})}))
    if decision == "allow":
        return None
    return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                               "permissionDecisionReason": reason}})


def _log_error(env, data, exc, event):
    """Exception type and a fixed code only: messages can carry config or prompt text."""
    try:
        sid = data.get("session_id") if isinstance(data, dict) else None
        route_log.append(host_state.state_dir(env), sid or "_errors",
                         {"event": "error", "type": type(exc).__name__, "code": f"{event}_failed"})
    except Exception:
        pass  # nothing left to do: fail open silently


HANDLERS = {"UserPromptSubmit": user_prompt_submit, "PreToolUse": pre_tool_use}


def main(event, plugin_root, stdin=None, stdout=None, env=None):
    """Always returns 0 and prints at most one JSON object."""
    env = os.environ if env is None else env
    data = None
    try:
        if env.get(GUARD_ENV) == "1":  # classifier child: never route recursively
            return 0
        data = json.loads((stdin or sys.stdin).read())
        out = HANDLERS[event](data, env, plugin_root)
        if out:
            print(out, file=stdout or sys.stdout)
    except Exception as exc:
        _log_error(env, data, exc, event)
    return 0

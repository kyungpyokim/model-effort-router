"""Codex Host Hook Adapter: stdin JSON -> Router Core -> advisory stdout JSON. Fails open (spec 3.7, spike)."""

import importlib
import json
import os
import sys
import time
from pathlib import Path

from ..context import refresh, summary
from ..context.transcripts import HARNESS_MESSAGE, MAX_TURN_CHARS, Turn, clip, read_turns
from ..difficulty.registry import BACKENDS
from ..difficulty.subscription import GUARD_ENV, SubscriptionBackend, codex_verified
from ..logging import route_log
from ..policy.config import resolve_config
from ..policy.router import route
from . import advice, hosts

REGISTRY_MODULE_ENV = "MER_TEST_REGISTRY_MODULE"  # tests only: a module under tests/ with register(registry, env)
USER_CONFIG_ENV = "MER_USER_CONFIG"
REPO_CONFIG = ".model-effort-router.json"
MAX_BACKEND_TIMEOUT_S = 12  # backend + fallback must fit in the 30s hook timeout with margin


def _registry(env, classifier_host=None):
    reg = dict(BACKENDS)
    if (
        reg.get("subscription") is SubscriptionBackend
    ):  # its CLI follows the host, which only hosts.get reads from the env
        name = classifier_host or hosts.get(env=env).name
        reg["subscription"] = lambda: SubscriptionBackend(host=name)
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
        env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"), "model-effort-router", "config.json"
    )
    return _load_json(Path(cwd) / REPO_CONFIG), _load_json(user_path)


def _context_output(event, text, notice=None):
    out = {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}
    if notice:  # user-visible line; additionalContext only reaches the model
        out["systemMessage"] = notice
    return json.dumps(out)


def _notice(plan):
    return f"[model-effort-router] {plan.decision.role} → {advice.effort_pair(plan.model, plan.applied_effort)}"


def _with_timeout(repo_cfg, timeout_s):
    repo_cfg = repo_cfg or {}
    return {**repo_cfg, "difficulty": {**repo_cfg.get("difficulty", {}), "timeout_s": timeout_s}}


def _session_context(data, host, sdir, sid, prompt, cfg, env, version_probe=None):
    """(context for the classifier, whether the background summary is due). ("", False) when disabled or unusable."""
    if not cfg.context_enabled or cfg.mode != "auto" or env.get(GUARD_ENV) == "1":
        return "", False
    try:
        turns = read_turns(data.get("transcript_path"), host.name)
        stored = summary.load(sdir, sid)
        base, fresh, _ = summary.pending(turns, stored)
        if fresh and fresh[-1] == Turn("user", clip(prompt.strip(), MAX_TURN_CHARS)):  # already written: it is the task
            fresh = fresh[:-1]
        due = (
            host.name in refresh.HOSTS
            and summary.needs_refresh(turns, stored)
            and (host.name != "codex" or codex_verified(version_probe))
        )
        return summary.build_context(base, fresh, cfg.context_max_chars), due
    except Exception as exc:  # the prompt alone still routes
        _log_error(env, data, exc, "SessionContext")
        return "", False


def user_prompt_submit(data, env, plugin_root, spawn=refresh.spawn, version_probe=None):
    prompt = data.get("prompt")
    if not isinstance(prompt, str) or HARNESS_MESSAGE.match(prompt):
        return None
    sid = data["session_id"]
    sdir = route_log.state_dir(env)
    repo_cfg, user_cfg = load_configs(data.get("cwd") or os.getcwd(), env)
    registry = _registry(env)
    cfg = resolve_config(repo=repo_cfg, user=user_cfg, registry=registry)
    clamped = cfg.timeout_s > MAX_BACKEND_TIMEOUT_S
    if clamped:
        repo_cfg = _with_timeout(repo_cfg, MAX_BACKEND_TIMEOUT_S)
    started = time.monotonic()
    host = hosts.get(env=env)
    context, due = _session_context(data, host, sdir, sid, prompt, cfg, env, version_probe)
    plan = None
    try:
        plan = route(
            prompt, repo_config=repo_cfg, user_config=user_cfg, registry=registry, host=host.name, context=context
        )
        latency_ms = (time.monotonic() - started) * 1000
    except Exception as exc:  # fail open, but leave a trace: a routing error must not look like a dropped prompt
        _append(
            env,
            data,
            sdir,
            sid,
            route_log.error_event(
                exc,
                latency_ms=(time.monotonic() - started) * 1000,
                prompt=prompt,
                configured_backend=cfg.backend,
                timeout_clamped=clamped,
            ),
        )
        return None
    finally:  # after routing, detached: the hook never waits for the summarizer
        if due and (plan.mode if plan else cfg.mode) != "off":
            try:
                spawn(host.name, sid, data["transcript_path"], sdir, env)
            except Exception as exc:
                _log_error(env, data, exc, "ContextRefresh")
    text = advice.render(plan, f"python3 {Path(plugin_root) / 'bin' / 'mer'}", host)
    out = _context_output("UserPromptSubmit", text, _notice(plan)) if text else None
    if plan.mode != "off":  # routing turned off by the user: nothing to record
        _append(
            env,
            data,
            sdir,
            sid,
            route_log.route_event(
                plan, latency_ms=latency_ms, prompt=prompt, configured_backend=cfg.backend, timeout_clamped=clamped
            ),
        )
    return out


def _append(env, data, sdir, sid, event):
    try:
        route_log.append(sdir, sid, event)
    except Exception as exc:
        _log_error(env, data, exc, "UserPromptSubmit")


def _log_error(env, data, exc, event):
    """Exception type and a fixed code only: messages can carry config or prompt text."""
    try:
        sid = data.get("session_id") if isinstance(data, dict) else None
        route_log.append(
            route_log.state_dir(env),
            sid or "_errors",
            {"event": "error", "type": type(exc).__name__, "code": f"{event}_failed"},
        )
    except Exception:
        pass  # nothing left to do: fail open silently


HANDLERS = {"UserPromptSubmit": user_prompt_submit}


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

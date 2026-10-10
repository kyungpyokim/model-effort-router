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
from ..policy.targeting import NO_ROUTE
from . import advice, hosts
from .main_model import main_model, normalize, save_session_model

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


def _notice(plan, same_model=None):
    if plan.target == NO_ROUTE and plan.mode == "auto":
        return advice.NO_ROUTE_MESSAGE
    line = f"[model-effort-router] {plan.decision.role} → {plan.agent} · {advice.effort_pair(plan.model, plan.applied_effort)}"
    if not same_model:
        return line
    return f"{line} — Main already runs this model; proceeding without a Subagent (routed effort {plan.applied_effort}; Main cannot change its own)"


def _main_model(data, host, env):
    try:
        return main_model(data, host.name, route_log.state_dir(env))
    except Exception as exc:  # unknown Main model: legacy advice
        _log_error(env, data, exc, "MainModel")
        return None


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
    cwd = data.get("cwd") or os.getcwd()
    repo_cfg, user_cfg = load_configs(cwd, env)
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
            prompt,
            repo_config=repo_cfg,
            user_config=user_cfg,
            registry=registry,
            host=host.name,
            context=context,
            repo_summary=os.path.basename(os.path.normpath(cwd)),
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
    main = _main_model(data, host, env) if plan.target != NO_ROUTE else None
    text = advice.render(plan, f"python3 {Path(plugin_root) / 'bin' / 'mer'}", host, main)
    out = _context_output("UserPromptSubmit", text, _notice(plan, advice.matches(plan, main))) if text else None
    if plan.mode != "off":  # routing turned off by the user: nothing to record
        _append(
            env,
            data,
            sdir,
            sid,
            route_log.route_event(
                plan,
                latency_ms=latency_ms,
                prompt=prompt,
                configured_backend=cfg.backend,
                timeout_clamped=clamped,
                host=host.name,
                turn_id=data.get("turn_id"),
                advice=advice.summary(plan, host, main),
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


def session_start(data, env, plugin_root):
    """Claude: remember the session's model for the first prompt, whose transcript does not exist yet. No output."""
    save_session_model(route_log.state_dir(env), data["session_id"], data.get("model"))


def post_model_switch(data, env, plugin_root):
    """Claude: record the new Main model at switch time. Must print nothing: hook stdout becomes model context."""
    save_session_model(route_log.state_dir(env), data["session_id"], data.get("to_model"), "switch")


MATCHED_ON = {"claude": ["agent_type"], "codex": ["model"]}  # the only fields each host's payload lets us compare
NO_CORRELATION = {"expected": None, "matched": None, "matched_on": []}


def _expected_matches(expected, host, agent_type, model):
    """True/False when the started Subagent equals/differs from the routed one; None when nothing is comparable.
    Always None after an inline_same_model route: no Subagent was asked for, so none can follow the advice."""
    if expected.get("action") == "inline_same_model":
        return None
    if host == "claude":  # the payload has no model; effort is not checked on either host
        wanted = (expected.get("invocation") or {}).get("subagent_type")
        return agent_type == wanted if wanted and agent_type else None
    routed, actual = normalize(expected.get("model")), normalize(model)
    return routed == actual if routed and actual else None


def _from_route(route_ev, host, agent_type, model):
    advice_ev = route_ev.get("advice") if route_ev else None
    if not isinstance(advice_ev, dict) or "routed_model" not in advice_ev:
        return NO_CORRELATION
    expected = {
        "model": advice_ev["routed_model"],
        "effort": advice_ev["routed_effort"],
        "agent": advice_ev["agent"],
        "action": advice_ev["action"],
        "invocation": advice_ev["invocation"],
    }
    return {
        "expected": expected,
        "matched": _expected_matches(expected, host, agent_type, model),
        "matched_on": MATCHED_ON[host],
    }


def _correlation(name, sdir, sid, host, data, model):
    """A start links to the session's latest route; a stop copies its own start's link (matched by agent_id)."""
    if name == "subagent_stop":
        start = route_log.last_event(sdir, sid, "subagent_start", agent_id=data.get("agent_id"))
        found = start.get("correlation") if start and data.get("agent_id") else None
        return found if isinstance(found, dict) else NO_CORRELATION
    return _from_route(route_log.last_event(sdir, sid, "route"), host, data.get("agent_type"), model)


def _subagent_event(name, data, env):
    """Record a Subagent lifecycle event. Ids, type and model only, never the Subagent's output. No stdout."""
    sid = data.get("session_id")
    if not sid:
        return
    sdir, host = route_log.state_dir(env), hosts.get(env=env).name
    model = data.get("model") if isinstance(data.get("model"), str) else None
    ev = {
        "event": name,
        "host": host,
        "agent_id": data.get("agent_id"),
        "agent_type": data.get("agent_type"),
        "model": model,
    }
    if data.get("turn_id") is not None:
        ev["agent_turn_id"] = data["turn_id"]  # Codex: the child's turn, not the route's
    ev["correlation"] = _correlation(name, sdir, sid, host, data, model)
    route_log.append(sdir, sid, ev)


def subagent_start(data, env, plugin_root):
    _subagent_event("subagent_start", data, env)


def subagent_stop(data, env, plugin_root):
    _subagent_event("subagent_stop", data, env)


HANDLERS = {
    "UserPromptSubmit": user_prompt_submit,
    "SessionStart": session_start,
    "PostModelSwitch": post_model_switch,
    "SubagentStart": subagent_start,
    "SubagentStop": subagent_stop,
}


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

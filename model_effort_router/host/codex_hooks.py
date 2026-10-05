"""Codex Host Hook Adapter: stdin JSON -> Router Core -> advisory stdout JSON. Fails open (spec 3.7, spike)."""
import importlib
import json
import os
import re
import sys
import time
from pathlib import Path

from ..difficulty.registry import BACKENDS
from ..difficulty.subscription import GUARD_ENV, SubscriptionBackend
from ..logging import route_log
from ..policy.config import resolve_config
from ..policy.router import route
from ..policy.targeting import NO_ROUTE
from . import advice, hosts

REGISTRY_MODULE_ENV = "MER_TEST_REGISTRY_MODULE"  # tests only: a module under tests/ with register(registry, env)
USER_CONFIG_ENV = "MER_USER_CONFIG"
REPO_CONFIG = ".model-effort-router.json"
# Messages the host itself puts in the user turn (a subagent's report, a background-task notice, a `!` shell
# command and its output, a slash-command echo): not the user's request, so never classified (no backend call).
HARNESS_MESSAGE = re.compile(
    r"\s*(?:Another Claude session sent a message:\s*)?(?:\[SYSTEM NOTIFICATION[^\]]*\]\s*)?"
    r"<(?:agent-message|cross-session-message|task-notification|bash-input|bash-stdout|bash-stderr"
    r"|local-command-stdout|local-command-caveat|command-name)\b")
MAX_BACKEND_TIMEOUT_S = 12  # backend + fallback must fit in the 30s hook timeout with margin


def _registry(env):
    reg = dict(BACKENDS)
    if reg.get("subscription") is SubscriptionBackend:  # its CLI follows the host, which only hosts.get reads from the env
        name = hosts.get(env=env).name
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
        env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"), "model-effort-router", "config.json")
    return _load_json(Path(cwd) / REPO_CONFIG), _load_json(user_path)


def _context_output(event, text):
    return json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}})


def _with_timeout(repo_cfg, timeout_s):
    repo_cfg = repo_cfg or {}
    return {**repo_cfg, "difficulty": {**repo_cfg.get("difficulty", {}), "timeout_s": timeout_s}}


def user_prompt_submit(data, env, plugin_root):
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
    plan = route(prompt, repo_config=repo_cfg, user_config=user_cfg, registry=registry, host=host.name)
    latency_ms = (time.monotonic() - started) * 1000
    if plan.target == NO_ROUTE and plan.decision is None:
        return None
    text = advice.render(plan, f'python3 {Path(plugin_root) / "bin" / "mer"}', host)
    out = _context_output("UserPromptSubmit", text) if text else None
    try:
        route_log.append(sdir, sid, route_log.route_event(
            plan, latency_ms=latency_ms, prompt=prompt, configured_backend=cfg.backend, timeout_clamped=clamped))
    except Exception as exc:
        _log_error(env, data, exc, "UserPromptSubmit")
    return out


def _log_error(env, data, exc, event):
    """Exception type and a fixed code only: messages can carry config or prompt text."""
    try:
        sid = data.get("session_id") if isinstance(data, dict) else None
        route_log.append(route_log.state_dir(env), sid or "_errors",
                         {"event": "error", "type": type(exc).__name__, "code": f"{event}_failed"})
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

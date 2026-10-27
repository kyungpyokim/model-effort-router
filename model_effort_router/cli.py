"""Route requests to a role, model, and effort."""

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time

from .host import hosts
from .host.advice import NO_ROUTE_MESSAGE, effort_pair
from .host.codex_hooks import REPO_CONFIG, USER_CONFIG_ENV, _registry, load_configs
from .logging import route_log
from .policy.config import resolve_config
from .policy.router import route
from .policy.targeting import NO_ROUTE
from .report import limit_count, since_seconds


class _RoutingInterrupted(BaseException):
    pass


class _RoutingSignalScope:
    @staticmethod
    def _terminate(_signum, _frame):
        raise _RoutingInterrupted("mer interrupted by SIGTERM")

    def __enter__(self):
        self.previous = None
        if threading.current_thread() is threading.main_thread():
            self.previous = signal.getsignal(signal.SIGTERM)
            signal.signal(signal.SIGTERM, self._terminate)
        return self

    def __exit__(self, *_exc):
        if self.previous is not None:
            signal.signal(signal.SIGTERM, self.previous)


def _parser():
    parser = argparse.ArgumentParser(prog="mer", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    route_parser = sub.add_parser("route", help="select a role, model, and effort for a request")
    route_parser.add_argument("request")
    route_parser.add_argument("--cwd", default=os.getcwd())
    route_parser.add_argument("--host", choices=sorted(hosts.HOSTS))
    route_parser.add_argument("--role")
    route_parser.add_argument("--effort")
    route_parser.add_argument("--json", action="store_true")
    route_parser.add_argument(
        "--automatic",
        action="store_true",
        help="skip requests MER does not classify for routing",
    )
    route_parser.add_argument("--session", help="host session id; records the route in that session's log")
    report = sub.add_parser("report", help="show routing and usage recorded in the session logs")
    report.add_argument("--session", help="session id prefix; default is every session")
    report.add_argument("--since", type=since_seconds, help="only events from the last <n>m, <n>h, or <n>d")
    report.add_argument(
        "--limit", type=limit_count, default=20, help="most recent rows to list, 0 for the summary only (default 20)"
    )
    mode_parser = sub.add_parser("mode", help="get or set router mode (on|off|auto|status)")
    mode_parser.add_argument("state", nargs="?", choices=["on", "off", "auto", "status"], default="status")
    mode_parser.add_argument(
        "--local", action="store_true", help="update repo-local config (.model-effort-router.json)"
    )
    mode_parser.add_argument("--cwd", default=os.getcwd())

    on_parser = sub.add_parser("on", help="enable model router (mode: auto)")
    on_parser.add_argument("--local", action="store_true", help="update repo-local config (.model-effort-router.json)")
    on_parser.add_argument("--cwd", default=os.getcwd())

    off_parser = sub.add_parser("off", help="disable model router (mode: off)")
    off_parser.add_argument("--local", action="store_true", help="update repo-local config (.model-effort-router.json)")
    off_parser.add_argument("--cwd", default=os.getcwd())

    status_parser = sub.add_parser("status", help="show current model router status")
    status_parser.add_argument("--cwd", default=os.getcwd())
    return parser


def _response(plan):
    decision = plan.decision
    return {
        "role": decision.role,
        "agent": plan.agent,
        "model": plan.model,
        "effort": plan.applied_effort,
        "requested_effort": plan.requested_effort,
        "risk_flags": list(plan.risk_flags),
        "classifier": decision.backend,
        "confidence": decision.confidence,
        "reason_code": decision.reason_code,
        "model_options": list(plan.model_options or ((plan.model,) if plan.model else ())),
    }


def _log_route(env, args, plan, latency_ms, host, repo_cfg, user_cfg, registry):
    """Record the route in the host session's log. Logging never fails a route."""
    try:
        backend = resolve_config(repo=repo_cfg, user=user_cfg, registry=registry).backend
        event = route_log.route_event(
            plan, latency_ms=latency_ms, prompt=args.request, configured_backend=backend, host=host
        )
        route_log.append(route_log.state_dir(env), args.session, event)
    except Exception as exc:
        print(f"mer: could not log route: {type(exc).__name__}", file=sys.stderr)


def _log_route_error(env, session_id, request, exc, latency_ms, host):
    if not session_id:
        return
    try:
        route_log.append(
            route_log.state_dir(env),
            session_id,
            route_log.error_event(exc, latency_ms=latency_ms, prompt=request, host=host),
        )
    except Exception as log_exc:
        print(f"mer: could not log route: {type(log_exc).__name__}", file=sys.stderr)


def _config_target(env, local, cwd):
    if local:
        return Path(cwd) / REPO_CONFIG
    home = env.get("HOME") or os.path.expanduser("~")
    user_path = env.get(USER_CONFIG_ENV) or os.path.join(
        env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"),
        "model-effort-router",
        "config.json",
    )
    return Path(user_path)


def _handle_mode(args, env, out):
    state = getattr(args, "state", None) or args.command
    if state in ("on", "off", "auto"):
        target_mode = "off" if state == "off" else "auto"
        local = getattr(args, "local", False)
        cwd = getattr(args, "cwd", os.getcwd())
        path = _config_target(env, local, cwd)
        cfg = {}
        if path.is_file():
            try:
                cfg = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                cfg = {}
        if not isinstance(cfg, dict):
            cfg = {}
        cfg.setdefault("router", {})["mode"] = target_mode
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        scope = f"local ({path.name})" if local else "global"
        if target_mode == "off":
            print(
                f"[model-effort-router] Router disabled (mode: off, scope: {scope}). Model routing is bypassed.",
                file=out,
            )
        else:
            print(f"[model-effort-router] Router enabled (mode: auto, scope: {scope}).", file=out)
        return 0

    # status
    cwd = getattr(args, "cwd", os.getcwd())
    repo_cfg, user_cfg = load_configs(cwd, env)
    cfg = resolve_config(repo=repo_cfg, user=user_cfg)
    active = "OFF" if cfg.mode == "off" else "ON"
    source = "default"
    if repo_cfg and "router" in repo_cfg and "mode" in repo_cfg["router"]:
        source = f"local {REPO_CONFIG}"
    elif user_cfg and "router" in user_cfg and "mode" in user_cfg["router"]:
        source = "global config.json"
    print(f"[model-effort-router] Status: {active} (mode: {cfg.mode}, source: {source})", file=out)
    return 0


def main(argv=None, *, env=None, out=None):
    out = out or sys.stdout
    env = dict(os.environ) if env is None else dict(env)
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("run", "chat"):
        print(f"mer {argv[0]} was removed; use `mer route` for model selection.", file=sys.stderr)
        return 2
    args = _parser().parse_args(argv)
    if args.command == "report":
        from .report import main as report_main

        return report_main(args, env=env, out=out)
    if args.command in ("mode", "on", "off", "status"):
        return _handle_mode(args, env=env, out=out)

    route_started = time.monotonic()
    host = None
    try:
        with _RoutingSignalScope():
            host = hosts.get(args.host, env)
            cwd = os.path.realpath(args.cwd)
            repo_cfg, user_cfg = load_configs(cwd, env)
            classifier_host = "codex" if host.name == "opencode" else host.name
            registry = _registry(env, classifier_host=classifier_host)
            plan = route(
                args.request,
                repo_config=repo_cfg,
                user_config=user_cfg,
                registry=registry,
                host=host.name,
                explicit=not args.automatic,
                role_override=args.role,
                effort_override=args.effort,
                repo_summary=os.path.basename(os.path.normpath(cwd)),
            )
    except _RoutingInterrupted as exc:
        _log_route_error(
            env,
            args.session,
            args.request,
            exc,
            (time.monotonic() - route_started) * 1000,
            getattr(host, "name", None),
        )
        print(f"mer: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        _log_route_error(
            env,
            args.session,
            args.request,
            exc,
            (time.monotonic() - route_started) * 1000,
            getattr(host, "name", None),
        )
        print(f"mer: could not route: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.session and plan.mode != "off":
        _log_route(
            env,
            args,
            plan,
            (time.monotonic() - route_started) * 1000,
            host.name,
            repo_cfg,
            user_cfg,
            registry,
        )
    if plan.override_rejected:
        print(
            "mer: invalid /router override; use `/router role=<role> effort=<effort>` or `/router mode=<mode>`",
            file=sys.stderr,
        )
        return 2
    if plan.decision is None or plan.target == NO_ROUTE:
        if args.automatic:
            response = {"route": "no_route", "mode": plan.mode}
            if plan.mode == "auto":
                response["message"] = NO_ROUTE_MESSAGE
            print(json.dumps(response) if args.json else "", file=out)
            return 0
        print("mer: routing is off, manual, or policy; provide an explicit --role and --effort", file=sys.stderr)
        return 2

    result = _response(plan)
    if args.json:
        print(json.dumps(result, ensure_ascii=False), file=out)
    else:
        model = result["model"]
        if host.name == "antigravity":  # its slug folds in the effort; display it separately like every other host
            model = model.removesuffix(f"-{result['effort']}")
        print(
            f"[model-effort-router] {result['role']} → {result['agent']} · {effort_pair(model, result['effort'])}",
            file=out,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

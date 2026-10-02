"""mer CLI: `python3 -m model_effort_router.cli run [--cwd DIR] [--dry-run] [--max-escalations N] "<request>"`.

Classifies the request (the configured backend, as the hooks do), then runs it as one Codex session with
cascade escalation and an independent review for high-risk work (spec 3.4). --dry-run starts no session and
never calls a model-calling classifier unless --classify is given; --level Lx fixes the level instead.
`mer chat "<request>"` classifies the same way, then replaces itself with an interactive `codex` session started
at the routed model/effort (no gate, escalation or review: the conversation is yours from there).
"""
import argparse
import json
import os
import shlex
import signal
import sys
import time
import uuid
from dataclasses import replace

from . import review as rv
from .difficulty.decision import LEVELS, DifficultyDecision
from .difficulty.registry import create
from .flow import PLAN_FIRST, SUBAGENT_HINT, WRAP_UP, run_flow
from .gate.run import load_gate_checks, run_gate
from .difficulty.subscription import SubscriptionBackend
from .host import hosts
from .host.codex_hooks import _registry, load_configs
from .logging import route_log
from .policy.config import resolve_config
from .policy.overrides import parse_override
from .policy.router import route
from .policy.session import REVIEW_DEFAULT, session_plan
from .policy.targeting import NO_ROUTE
from .profiles.profiles import parse_profile

GATE_TIMEOUT_S = 300


class Terminated(BaseException):
    """SIGTERM (an outer timeout): unwinds the running codex call so its process group is stopped too.
    BaseException so the flow's per-step `except Exception` handlers cannot swallow it and carry on."""


def _raise_terminated(signum, frame):
    raise Terminated("mer received SIGTERM")


class _FixedLevel:
    """Stands in for every backend in a --dry-run --level run: no classifier call."""
    name = "dry-run"

    def __init__(self, level):
        self.level = level

    def classify(self, task, timeout_s):
        return DifficultyDecision(level=self.level, backend=self.name)


def _calls_model(cfg, registry):
    """Backends in the chain that may call a model. Fail closed: only an explicit `calls_model = False` counts
    as offline (checked on an instance, so function/partial factories are covered too; creating one calls nothing)."""
    names = [cfg.backend] + ([cfg.fallback] if cfg.fallback != "none" else [])
    return [n for n in names if getattr(create(n, registry), "calls_model", True) is not False]


def _fmt(p, host):
    r = host.resolve(p)
    return f"{p.tier}:{p.effort} -> {r.model}/{r.applied_effort or 'no effort flag'}" + (
        f" (requested {r.requested_effort})" if r.requested_effort != r.applied_effort else "")


def _first_argv(target, sp, text, host):
    cx = host.exec
    if target == "plan_only":
        return cx.session_argv(sp.plan_profile, f"{text}\n\nWrite an implementation plan only. Do not modify any files.", "read-only")
    if target == "review_only":
        return cx.session_argv(sp.review or REVIEW_DEFAULT, "<review prompt: request + git diff + gate JSON>", "read-only",
                               subagents=sp.review_subagents)
    n = sp.implement_subagents
    return cx.session_argv(sp.start, f"{text}\n\n{PLAN_FIRST if sp.plan_first else ''}{SUBAGENT_HINT if n else ''}{WRAP_UP}",
                           "workspace-write", subagents=n)


def _dry_run_text(plan, sp, text, host):
    d = plan.decision
    ladder = "; ".join(f"{i}. {_fmt(p, host)}" for i, p in enumerate(sp.ladder, 1)) or "none"
    lines = [f"host: {host.name}", f"level: {sp.level or 'manual'}" + (f" (backend {d.backend})" if d else ""),
             f"target: {plan.target}", f"risk flags: {', '.join(plan.risk_flags) or 'none'}",
             f"session: {_fmt(sp.start, host)}", f"plan first: {'yes' if sp.plan_first else 'no'}",
             f"review: {_fmt(sp.review, host) if sp.review else 'none'}",
             f"ladder: {ladder} (then stop and report)", f"rules: {', '.join(sp.applied_rules)}",
             "first command: " + shlex.join(_first_argv(plan.target, sp, text, host))]
    return "\n".join(lines)


def _human(out):
    r = out["review"]
    lines = [f"mer: {out['status']} (level {out['level'] or '-'}, target {out['target']})"]
    if out.get("profile"):
        lines.append(f"session: {out['profile']['model']}/{out['profile']['applied_effort']}, escalations {out['escalations']}")
    lines.append(f"gate: {out['gate'] or 'not run'}; review: {r['verdict'] or r['skipped'] or '-'}")
    u = out["usage"]
    lines.append(f"usage: {u['total']} tokens (in {u['input']}, out {u['output']}) over {len(out['calls'])} call(s)")
    if out.get("error"):
        lines.append(f"error: {out['error']}")
    if out["status"] in ("changes_requested", "review_fixed") and r.get("text"):
        lines += ["", "review findings:", r["text"]]
    if out.get("message"):
        lines += ["", out["message"]]
    return "\n".join(lines)


def _chat_argv(target, sp, text, cwd, host):
    """Interactive session at the routed profile; plan/review-only requests stay read-only."""
    readonly = target in ("plan_only", "review_only")
    if target == "plan_only":
        profile = sp.plan_profile
    elif target == "review_only":
        profile = sp.review or REVIEW_DEFAULT
    else:
        profile = sp.start
        text = f"{text}\n\n{PLAN_FIRST.strip()}" if sp.plan_first else text
    r = host.resolve(profile)
    if host.name == "claude":  # no cwd flag: the caller chdirs; `plan` permission mode is read-only
        effort = ["--effort", r.applied_effort] if r.applied_effort else []
        return ["claude", "--model", r.model, *effort, *(["--permission-mode", "plan"] if readonly else []), "--", text], profile
    return ["codex", "--cd", cwd, "-m", r.model, "-c", f"model_reasoning_effort={r.applied_effort}",
            *(["-s", "read-only"] if readonly else []), text], profile


def _chat_note(plan, sp, profile, host):
    d = plan.decision
    note = (f"mer chat: {d.level if d else 'manual'}, risk flags {', '.join(plan.risk_flags) or 'none'} -> "
            f"{_fmt(profile, host)}. No gate/escalation/review here; switch with {host.switch_hint} if the task grows.")
    if sp.review and plan.target == "route":
        note += (f"\nThis work warrants an independent review afterwards: mer run --review-profile "
                 f"{sp.review.tier}:{sp.review.effort} 'review only: check the current diff for <the task>'")
    return note


def _parser():
    ap = argparse.ArgumentParser(prog="mer", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("request")
    common.add_argument("--cwd", default=os.getcwd())
    common.add_argument("--dry-run", action="store_true", help="print decision and the first command only")
    common.add_argument("--level", choices=LEVELS, help="--dry-run only: use this level instead of classifying")
    common.add_argument("--classify", action="store_true",
                        help="--dry-run only: allow one classifier call (uses model quota)")
    common.add_argument("--host", choices=sorted(hosts.HOSTS), help="codex or claude (default: $MER_HOST, else codex)")
    sub.add_parser("chat", parents=[common], help="route, then start the interactive host CLI at that model/effort")
    run = sub.add_parser("run", parents=[common], help="route and run a request")
    run.add_argument("--review-profile", type=parse_profile, metavar="TIER:EFFORT",
                     help="minimum profile of the independent review (never lowers the computed one)")
    run.add_argument("--max-escalations", type=int, default=2)
    run.add_argument("--timeout", type=float, default=1200.0, help="seconds per codex call")
    run.add_argument("--json", action="store_true", help="machine-readable output")
    run.add_argument("--exit-zero", action="store_true", help="exit 0 after any completed run (outcome stays in the output)")
    return ap


def main(argv=None, **kw):
    """SIGTERM (an outer timeout) at any point, classification included, stops the running codex child too:
    codex children live in their own process groups, so mer must stop them itself."""
    previous = signal.signal(signal.SIGTERM, _raise_terminated)
    try:
        return _main(argv, **kw)
    except Terminated:
        print("mer: terminated (SIGTERM); the running codex call was stopped", file=sys.stderr)
        return 143
    finally:
        signal.signal(signal.SIGTERM, previous)


def _main(argv=None, *, env=None, runner=None, gate_fn=None, diff_fn=rv.git_diff, out=None,
          exec_fn=os.execvpe):
    out = out or sys.stdout
    env = dict(os.environ) if env is None else env
    args = _parser().parse_args(argv)
    try:
        host = hosts.get(args.host, env)
    except ValueError as exc:
        print(f"mer: {exc}", file=sys.stderr)
        return 2
    cx = host.exec
    chat = args.command == "chat"
    if not chat and args.max_escalations < 0:
        print("mer: --max-escalations must be >= 0", file=sys.stderr)
        return 2
    if (args.level or args.classify) and not args.dry_run:
        print("mer: --level and --classify only apply with --dry-run", file=sys.stderr)
        return 2
    cwd = os.path.realpath(args.cwd)
    try:
        repo_cfg, user_cfg = load_configs(cwd, env)
        registry = _registry(env)
        if registry.get("subscription") is SubscriptionBackend:  # its CLI follows the host (claude -p on Haiku vs codex exec)
            registry = {**registry, "subscription": lambda: SubscriptionBackend(host=host.name)}
        cfg = resolve_config(task=parse_override(args.request)[0].as_config(), repo=repo_cfg, user=user_cfg,
                             registry=registry)
        if args.level:
            registry = {name: (lambda: _FixedLevel(args.level)) for name in registry}
        elif args.dry_run and not args.classify and cfg.mode == "auto" and _calls_model(cfg, registry):
            print(f"mer: --dry-run would call the {'/'.join(_calls_model(cfg, registry))} classifier; "
                  "pass --level L1..L5, or --classify to allow one call", file=sys.stderr)
            return 2
        started = time.monotonic()
        plan = route(args.request, repo_config=repo_cfg, user_config=user_cfg, registry=registry, explicit=True)
        latency_ms = (time.monotonic() - started) * 1000
    except Exception as exc:
        print(f"mer: could not route: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if plan.override_rejected:
        print("mer: the /router line was not understood; nothing was run", file=sys.stderr)
        return 2
    if plan.target == NO_ROUTE:
        if chat:  # the user still asked for a conversation: start one with their own defaults
            plain = parse_override(args.request)[1].strip()
            return _exec(["claude", "--", plain] if host.name == "claude" else ["codex", "--cd", cwd, plain],
                         cx.session_env(env), exec_fn, args.dry_run, out,
                         f"mer chat: routing is {plan.mode}; starting {host.name} with your defaults", cwd, host)
        print(f"mer: routing is {plan.mode}; nothing was run", file=out)
        return 0

    _, text = parse_override(args.request)
    text = text.strip()
    try:
        sp = session_plan(plan.decision, plan.risk_flags, plan.overrides, cfg.subagent_policy)
        if getattr(args, "review_profile", None):  # carried from hook advice: a re-classified review request must not drop the floor
            base = sp.review or (REVIEW_DEFAULT if plan.target == "review_only" else None)
            sp = replace(sp, review=args.review_profile.at_least(base) if base else args.review_profile)
    except ValueError as exc:  # manual mode without a session profile
        print(f"mer: {exc}", file=sys.stderr)
        return 2
    if chat:
        argv, profile = _chat_argv(plan.target, sp, text, cwd, host)
        if not args.dry_run:
            try:
                route_log.append(route_log.state_dir(env), f"mer-chat-{int(time.time())}-{uuid.uuid4().hex[:6]}",
                                 {**route_log.route_event(plan, latency_ms=latency_ms, prompt=args.request,
                                                          configured_backend=cfg.backend),
                                  "session_plan": sp.to_dict(), "source": "mer chat"})
            except OSError:
                pass  # logging must never decide the outcome
        return _exec(argv, cx.session_env(env), exec_fn, args.dry_run, out, _chat_note(plan, sp, profile, host), cwd, host)
    if args.dry_run:
        print(_dry_run_text(plan, sp, text, host), file=out)
        return 0

    sdir, sid = route_log.state_dir(env), f"mer-{int(time.time())}-{uuid.uuid4().hex[:6]}"

    def emit(event):
        try:
            route_log.append(sdir, sid, event)
        except OSError:
            pass  # logging must never decide the outcome

    emit({**route_log.route_event(plan, latency_ms=latency_ms, prompt=args.request,
                                  configured_backend=cfg.backend), "session_plan": sp.to_dict(), "source": "mer"})
    gate_fn = gate_fn or (lambda c: run_gate(c, load_gate_checks(c, env), GATE_TIMEOUT_S))
    result = run_flow(text, sp, cwd=cwd, runner=runner or cx.run_subprocess, env=env, host=host, gate_fn=gate_fn, diff_fn=diff_fn, emit=emit,
                      target=plan.target, max_escalations=args.max_escalations, timeout_s=args.timeout)
    d = plan.decision
    result.update(session_id=sid, risk_flags=list(plan.risk_flags), backend=d.backend if d else None,
                  session_plan=sp.to_dict())
    print(json.dumps(result, ensure_ascii=False) if args.json else _human(result), file=out)
    return 0 if args.exit_zero else result["exit_code"]


def _exec(argv, env, exec_fn, dry_run, out, note, cwd, host):
    """Replace mer with the host CLI (keeps the terminal). `session_env` sets the guard: the plugin hook stays quiet in it.
    claude has no cwd flag, so mer changes directory first."""
    print(note, file=sys.stderr)
    if dry_run:
        print("command: " + shlex.join(argv), file=out)
        if host.name == "claude":
            print(f"cwd: {cwd}", file=out)
        return 0
    try:
        if host.name == "claude":
            os.chdir(cwd)
        exec_fn(argv[0], argv, env)
    except OSError as exc:
        print(f"mer: could not start {host.name}: {exc}", file=sys.stderr)
        return 127
    return 0  # only reached with an injected exec_fn


if __name__ == "__main__":
    sys.exit(main())

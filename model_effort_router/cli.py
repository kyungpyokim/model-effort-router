"""Route requests; run once or opt into low-first verification and promotion."""
import argparse
import hashlib
import json
import os
import signal
import shlex
import stat
import subprocess
import sys
import threading
import time
import uuid
from math import isfinite

from .difficulty.subscription import SubscriptionBackend
from .difficulty.decision import merge_risk_flags
from .difficulty.risk import detect_risk_flags
from .flow import WorkerInterrupted, run_low_first, run_worker
from .host import hosts
from .host.codex_hooks import _registry, load_configs
from .logging import route_log
from .policy.overrides import parse_override
from .policy.router import route
from .review import _git, git_diff


_ONE_WAY_FLAGS = frozenset(("data_migration", "data_loss", "payment"))


def _changed_paths(diff):
    return [*(diff.get("files") or []), *(diff.get("untracked") or [])] if diff.get("is_repo") else []


def _path_state(cwd, path):
    full_path = os.path.join(cwd, path)
    try:
        info = os.lstat(full_path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        return ("unreadable", exc.errno)
    if stat.S_ISLNK(info.st_mode):
        try:
            return ("link", os.readlink(full_path))
        except FileNotFoundError:
            return None
        except OSError as exc:
            return ("unreadable", exc.errno)
    if stat.S_ISREG(info.st_mode):
        digest = hashlib.sha256()
        try:
            with open(full_path, "rb") as source:
                for block in iter(lambda: source.read(65536), b""):
                    digest.update(block)
        except OSError as exc:
            return ("unreadable", exc.errno)
        return ("file", info.st_mode & 0o777, digest.digest())
    return ("other", info.st_mode, info.st_size, info.st_mtime_ns)


def _change_summary(paths, flags):
    if not paths:
        return None
    # ponytail: top-level path buckets approximate impact; domain review supplies the real blast radius.
    top_dirs = len({path.split("/", 1)[0] for path in paths if "/" in path})
    return {"door": "one-way" if _ONE_WAY_FLAGS.intersection(flags) else "two-way",
            "blast_radius": "local" if top_dirs <= 1 else "broad",
            "files": len(paths), "top_dirs": top_dirs, "risk_flags": list(flags)}


class _WorkerSignalScope:
    @staticmethod
    def _terminate(_signum, _frame):
        raise WorkerInterrupted("mer interrupted by SIGTERM")

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
    for command in ("route", "run"):
        item = sub.add_parser(command)
        item.add_argument("request")
        item.add_argument("--cwd", default=os.getcwd())
        item.add_argument("--host", choices=sorted(hosts.HOSTS))
        item.add_argument("--role")
        item.add_argument("--effort")
        item.add_argument("--json", action="store_true")
        if command == "run":
            item.add_argument("--timeout", type=float, default=1200.0)
            item.add_argument("--low-first", action="store_true", help="promote effort only after verification fails")
            item.add_argument("--verify", help="fixed verification command (argv, no shell operators)")
            item.add_argument("--verify-timeout", type=float, default=300.0)
            item.add_argument("--retry-low", action="store_true", help="retry low once before promoting, for comparison")
            item.add_argument("--approve-xhigh", action="store_true", help="explicit user approval for xhigh in this run")
    old = sub.add_parser("chat", help="removed; use mer route and ask Main to call a Subagent")
    old.add_argument("request", nargs="?")
    return parser


def _response(plan):
    d = plan.decision
    return {"role": d.role, "agent": plan.agent, "model": plan.model, "effort": plan.applied_effort,
            "requested_effort": plan.requested_effort, "risk_flags": list(plan.risk_flags),
            "classifier": d.backend, "confidence": d.confidence, "reason_code": d.reason_code,
            "fallback_model": plan.fallback_model, "fallback_reason": plan.fallback_reason}


def main(argv=None, *, env=None, runner=None, out=None):
    out = out or sys.stdout
    env = dict(os.environ) if env is None else dict(env)
    args = _parser().parse_args(argv)
    if args.command == "chat":
        print("mer chat was removed; use `mer route` and have Main invoke the selected Subagent with a Context Packet.", file=sys.stderr)
        return 2
    if args.command == "run":
        if any(not isfinite(v) or v <= 0 for v in (args.timeout, args.verify_timeout)):
            print("mer: timeouts must be positive and finite", file=sys.stderr)
            return 2
        if args.low_first != (args.verify is not None) or (args.low_first and not args.verify.strip()) \
                or args.retry_low and not args.low_first:
            print("mer: --low-first requires --verify; --verify and --retry-low require --low-first", file=sys.stderr)
            return 2
    try:
        with _WorkerSignalScope():
            host = hosts.get(args.host, env)
            cwd = os.path.realpath(args.cwd)
            repo_cfg, user_cfg = load_configs(cwd, env)
            registry = _registry(env)
            if registry.get("subscription") is SubscriptionBackend:
                registry["subscription"] = lambda: SubscriptionBackend(host=host.name)
            plan = route(args.request, repo_config=repo_cfg, user_config=user_cfg, registry=registry,
                         host=host.name, explicit=True, role_override=args.role, effort_override=args.effort)
    except WorkerInterrupted as exc:
        print(f"mer: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"mer: could not route: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if plan.override_rejected:
        print("mer: invalid /router override; use `/router role=<role> effort=<effort>` or `/router mode=<mode>`", file=sys.stderr)
        return 2
    if plan.decision is None:
        print("mer: routing is off or manual; provide an explicit --role and --effort", file=sys.stderr)
        return 2
    result = _response(plan)
    if args.command == "route":
        print(json.dumps(result, ensure_ascii=False) if args.json else
              f"{result['role']} → {result['agent']} / {result['model']} / {result['effort']}", file=out)
        return 0
    if host.name == "antigravity":
        print("mer: Antigravity Subagent execution is unsupported because execution isolation is unverified; use `mer route`.", file=sys.stderr)
        return 2
    if host.name == "opencode":
        print("mer: OpenCode worker execution is unsupported; use `mer route` for advice.", file=sys.stderr)
        return 2
    if not args.low_first and plan.applied_effort == "xhigh" and not args.approve_xhigh:
        result = {**result, "status": "approval_required", "approval_required": True, "next_effort": "xhigh",
                  "error": "User approval is required before xhigh; pass --approve-xhigh only after approval."}
        print(json.dumps(result, ensure_ascii=False) if args.json else result["error"], file=out)
        return 1
    start_effort = "low"
    if args.low_first:
        from .difficulty.decision import EFFORTS, EXECUTION_ROLES
        from .gate.discovery import Check
        from .gate.run import run_check
        from .policy.config import resolve_config
        try:
            if plan.decision.role not in EXECUTION_ROLES:
                raise ValueError("--low-first requires implementation, fix, lint, or test")
            if plan.decision.backend == "explicit" and plan.requested_effort != "low":
                if plan.requested_effort != "xhigh" or not args.approve_xhigh or args.retry_low:
                    raise ValueError("--low-first needs low or explicitly approved xhigh without --retry-low")
                start_effort = "xhigh"
            mapped = resolve_config(repo=repo_cfg, user=user_cfg, registry=registry).models[host.name]["execution"]
            if not set(EFFORTS).issubset(mapped["efforts"]):
                raise ValueError("--low-first requires model support for low, medium, high, xhigh")
            if not shlex.split(args.verify):
                raise ValueError("--verify must be a non-empty command")
            check = Check("test", args.verify, "--verify", False)
        except ValueError as exc:
            print(f"mer: {exc}", file=sys.stderr)
            return 2
    _, task = parse_override(args.request)
    task = task.strip()
    packet = _context_packet(task, cwd, plan)
    baseline_paths = _changed_paths(git_diff(cwd))
    try:
        root_status, root_output = _git(["rev-parse", "--show-toplevel"], cwd)
        path_root = os.path.realpath(root_output.strip()) if root_status == 0 else cwd
    except (OSError, subprocess.SubprocessError):
        path_root = cwd
    baseline_states = {path: _path_state(path_root, path) for path in baseline_paths}
    sid = f"mer-{int(time.time())}-{uuid.uuid4().hex[:6]}"
    started = time.monotonic()
    try:
        with _WorkerSignalScope():
            options = dict(cwd=cwd, runner=runner or host.exec.run_subprocess,
                           env=env, host=host, timeout_s=args.timeout, context_packet=packet)
            if args.low_first:
                result = run_low_first(task, plan, **options, verify=lambda root, timeout: run_check(check, root, timeout),
                                       verify_timeout_s=args.verify_timeout, retry_low=args.retry_low,
                                       approve_xhigh=args.approve_xhigh, start_effort=start_effort)
            else:
                result = run_worker(task, plan, **options)
    except WorkerInterrupted as exc:
        result = {**result, **(exc.result or {}), "model": exc.model or result.get("model", plan.model),
                  "fallback_reason": exc.fallback_reason or result.get("fallback_reason"),
                  "status": "error", "error": str(exc)[:300]}
        status = 1
    except Exception as exc:
        result = {**result, "model": getattr(exc, "model", result.get("model", plan.model)),
                  "fallback_reason": getattr(exc, "fallback_reason", result.get("fallback_reason")),
                  "status": "error", "error": f"{type(exc).__name__}: {exc}"[:300]}
        status = 1
    else:
        result = {**result, "status": result.get("status", "complete")}
        status = 0 if result["status"] == "complete" else 1
    if args.low_first:
        policy = "xhigh-continuation" if start_effort == "xhigh" else "low-retry" if args.retry_low else "low-first"
        result = {**result, "policy": policy,
                  "classifier_usage": plan.classifier_usage, "classifier_usage_missing": plan.classifier_usage_missing}
    final_paths = _changed_paths(git_diff(cwd))
    changed_paths = [path for path in dict.fromkeys((*baseline_paths, *final_paths))
                     if path not in baseline_states or _path_state(path_root, path) != baseline_states[path]]
    result_flags = merge_risk_flags(plan.risk_flags, detect_risk_flags("", changed_paths))
    result = {**result, "risk_flags": list(result_flags),
              "change": _change_summary(changed_paths, result_flags)}
    result["wall_s"] = round(time.monotonic() - started, 3)
    try:
        route_log.append(route_log.state_dir(env), sid, {"event": "run", "role": plan.decision.role,
            "agent": plan.agent, "requested_model": plan.model, "actual_model": result.get("model", plan.model),
            "requested_effort": plan.requested_effort, "applied_effort": result.get("applied_effort", plan.applied_effort),
            "classifier": plan.decision.backend, "fallback_reason": result.get("fallback_reason"),
            "status": result.get("status", "error"), "usage": result.get("usage"), "wall_s": result["wall_s"],
            **({"policy": result.get("policy"), "first_pass": result.get("first_pass"),
                "escalation_count": result.get("escalation_count"), "usage_missing": result.get("usage_missing"),
                "usage_scope": result.get("usage_scope"),
                "classifier_usage": plan.classifier_usage, "classifier_usage_missing": plan.classifier_usage_missing,
                "approval_required": result.get("approval_required", False),
                "attempts": [{k: a.get(k) for k in ("model", "fallback_reason", "applied_effort", "usage", "worker_wall_s")}
                             | {"verification_status": a.get("verification", {}).get("status"),
                                "verification_duration_s": a.get("verification", {}).get("duration_s")}
                             for a in result.get("attempts", [])]} if args.low_first else {})})
    except OSError:
        pass
    if args.json:
        print(json.dumps(result, ensure_ascii=False), file=out)
    else:
        lines = [result.get("error", result.get("message", ""))]
        change = result.get("change")
        if change:
            lines.append(f"Door: {change['door']}; Blast Radius: {change['blast_radius']} "
                         f"({change['files']} file(s), {change['top_dirs']} top-level directories)")
        print("\n".join(line for line in lines if line), file=out)
    return status


def _context_packet(task, cwd, plan):
    if plan.decision.role == "review":
        from .review import git_diff
        diff = git_diff(cwd)
        diff_text = diff.get("diff", "")
        untracked = diff.get("untracked") or []
        if untracked:
            diff_text += "\nUntracked file paths (inspect from workspace):\n" + "\n".join(untracked)
        return json.dumps({"goal": task, "decisions": [], "constraints": ["Review only; do not edit files."],
                           "diff": diff_text, "verification": []}, ensure_ascii=False)
    return json.dumps({"task": task, "context": [], "decisions": [], "constraints": [],
                       "relevant_files": [], "expected_result": "Complete the requested task and report verification."},
                      ensure_ascii=False)


if __name__ == "__main__":
    sys.exit(main())

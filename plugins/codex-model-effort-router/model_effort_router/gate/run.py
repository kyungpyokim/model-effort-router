"""Run discovered checks and print JSON: passed / failed / not_run per check (spec 15). CLI: bin/mer-gate."""
import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

from ..host import state as host_state
from ..host.codex_hooks import load_configs
from ..logging import route_log
from .discovery import KINDS, discover

DEFAULT_TIMEOUT_S = 300
TAIL_CHARS = 2000
MARKABLE = ("done", "failed", "cancelled")


def _kill_group(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass


def run_check(check, cwd, timeout_s):
    try:
        argv = check.command if check.shell else shlex.split(check.command)
        start = time.monotonic()
        proc = subprocess.Popen(
            argv, shell=check.shell, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, errors="replace", start_new_session=True,
        )
    except (OSError, ValueError) as exc:
        return {"status": "failed", "command": check.command, "source": check.source,
                "reason": f"could not start: {type(exc).__name__}"}
    reason, out = None, ""
    try:
        try:
            out, _ = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            reason = f"timeout after {timeout_s}s"
            _kill_group(proc)
            try:
                out, _ = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                out = ""
    finally:
        _kill_group(proc)  # also reaps grandchildren left behind after a normal exit
    result = {"status": "passed" if proc.returncode == 0 and not reason else "failed",
              "command": check.command, "source": check.source, "exit_code": proc.returncode,
              "duration_s": round(time.monotonic() - start, 2), "output_tail": (out or "")[-TAIL_CHARS:]}
    if reason:
        result["reason"] = reason
    return result


def run_gate(cwd, config_checks, timeout_s):
    found = discover(cwd, config_checks)
    checks = {k: run_check(c, cwd, timeout_s) if c else
              {"status": "not_run", "reason": "no command discovered"} for k, c in found.items()}
    statuses = {c["status"] for c in checks.values()}
    overall = "failed" if "failed" in statuses else "incomplete" if "not_run" in statuses else "passed"
    return {"checks": checks, "overall": overall}


def _gate_checks(layer):
    if layer is None or "gate" not in layer:
        return {}
    gate = layer["gate"]
    checks = gate.get("checks", {}) if isinstance(gate, dict) else None
    if not isinstance(checks, dict):
        raise ValueError("gate.checks must be an object")
    return checks


def load_gate_checks(cwd, env):
    """User gate.checks overlaid by repo gate.checks, per kind."""
    repo, user = load_configs(cwd, env)
    return {**_gate_checks(user), **_gate_checks(repo)}


def _with_state(sdir, session_id, fn):
    with host_state.locked(sdir, session_id):
        st = host_state.load(sdir, session_id)
        fn(st)


def main(argv=None, env=None):
    env = os.environ if env is None else env
    ap = argparse.ArgumentParser(prog="mer-gate", description="Deterministic Test Gate")
    ap.add_argument("--cwd", default=os.getcwd())
    ap.add_argument("--session")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    ap.add_argument("--mark", nargs=2, metavar=("STAGE", "STATUS"),
                    help=f"record a stage outcome ({'/'.join(MARKABLE)}); needs --session")
    ap.add_argument("--review", choices=route_log.REVIEW_VERDICTS,
                    help="record the review verdict in the route log; needs --session")
    ap.add_argument("--findings", type=int, help="number of review findings (with --review)")
    args = ap.parse_args(argv)
    if args.review and args.mark:
        ap.error("--review and --mark are mutually exclusive")
    if args.findings is not None and (not args.review or args.findings < 0):
        ap.error("--findings needs --review and must be >= 0")
    sdir = host_state.state_dir(env)

    if args.review:
        if not args.session:
            ap.error("--review needs --session")
        st = host_state.load(sdir, args.session)
        ev = route_log.review_event(args.review, args.findings, st["fix_count"] if st else None)
        route_log.append(sdir, args.session, ev)
        print(json.dumps(ev))
        return 0

    if args.mark:
        if not args.session:
            ap.error("--mark needs --session")
        stage, status = args.mark
        if status not in MARKABLE:
            ap.error(f"status must be one of {MARKABLE}")

        def mark(st):
            if st is None or stage not in st["stages"]:
                ap.error(f"no such stage in this session's plan: {stage}")
            st["stages"][stage]["status"] = status
            host_state.save(sdir, args.session, st)

        _with_state(sdir, args.session, mark)
        route_log.append(sdir, args.session, {"event": "stage_mark", "stage": stage, "status": status})
        print(json.dumps({"stage": stage, "status": status}))
        return 0

    try:
        result = run_gate(args.cwd, load_gate_checks(args.cwd, env), args.timeout)
    except Exception as exc:  # bad config: report as JSON, never a traceback
        print(json.dumps({"overall": "failed", "error": f"invalid gate configuration: {exc}"}))
        return 1
    if args.session:
        def record(st):
            if st is not None:
                impl = st["stages"].get("implement")
                if impl and impl["status"] == "running":
                    impl["status"] = "done"
                    host_state.save(sdir, args.session, st)

        _with_state(sdir, args.session, record)
        route_log.append(sdir, args.session, {"event": "gate", "overall": result["overall"],
                                              "checks": {k: v["status"] for k, v in result["checks"].items()}})
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

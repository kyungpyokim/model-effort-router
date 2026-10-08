"""Run discovered checks and print JSON: passed / failed / not_run per check (spec 15). CLI: bin/mer-gate."""

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import time

from ..host.codex_hooks import load_configs
from .discovery import discover

DEFAULT_TIMEOUT_S = 300
TAIL_CHARS = 2000


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
            argv,
            shell=check.shell,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            start_new_session=True,
        )
    except (OSError, ValueError) as exc:
        return {
            "status": "failed",
            "command": check.command,
            "source": check.source,
            "reason": f"could not start: {type(exc).__name__}",
        }
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
    result = {
        "status": "passed" if proc.returncode == 0 and not reason else "failed",
        "command": check.command,
        "source": check.source,
        "exit_code": proc.returncode,
        "duration_s": round(time.monotonic() - start, 2),
        "output_tail": (out or "")[-TAIL_CHARS:],
    }
    if reason:
        result["reason"] = reason
    return result


def run_gate(cwd, config_checks, timeout_s):
    found = discover(cwd, config_checks)
    checks = {
        k: run_check(c, cwd, timeout_s) if c else {"status": "not_run", "reason": "no command discovered"}
        for k, c in found.items()
    }
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


def _probe_nudge(layer):
    gate = (layer or {}).get("gate")
    if not isinstance(gate, dict) or "probe_nudge" not in gate:
        return None
    if not isinstance(gate["probe_nudge"], bool):
        raise ValueError("gate.probe_nudge must be true or false")
    return gate["probe_nudge"]


def probe_nudge_setting(repo, user):
    """gate.probe_nudge of the loaded config layers: repo over user, off when neither sets it. Both are validated."""
    repo, user = _probe_nudge(repo), _probe_nudge(user)
    return next((v for v in (repo, user) if v is not None), False)


def main(argv=None, env=None):
    env = os.environ if env is None else env
    ap = argparse.ArgumentParser(prog="mer-gate", description="Deterministic Test Gate")
    ap.add_argument("--cwd", default=os.getcwd())
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    args = ap.parse_args(argv)
    try:
        result = run_gate(args.cwd, load_gate_checks(args.cwd, env), args.timeout)
    except Exception as exc:  # bad config: report as JSON, never a traceback
        print(json.dumps({"overall": "failed", "error": f"invalid gate configuration: {exc}"}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

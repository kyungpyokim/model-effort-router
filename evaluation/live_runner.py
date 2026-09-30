"""Live Baseline-vs-Router runner (spec 22.3). Executes `codex exec` -> CONSUMES SUBSCRIPTION USAGE.

Only runs with --live; without it, prints the commands it would run (dry-run). Tests inject a fake runner.
Every run works in ONE fixed eval workdir (default: <state dir>/eval-workdir, realpath'd), reset from the fixture
before and cleared after each run; the fixture itself is never modified. Codex persists one `trust_level` entry
for that path in ~/.codex/config.toml.
Baseline copy has `.codex/` removed and MER_CLASSIFIER=1 set (the Router hook no-ops under that guard);
a baseline run that still shows router activity is marked `contaminated`.
Router runs are valid only if the plugin is installed and its hooks trusted BY YOU beforehand (this tool never
bypasses hook trust); a router run whose log has no `route` and `stage_spawn` event gets router_active=false.
Usage: python3 -m evaluation.live_runner --cases CORPUS --fixture DIR --out RUNS.jsonl [--model M] [--limit N] [--live]
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

from model_effort_router.difficulty.subscription import default_runner
from model_effort_router.difficulty.usage import sum_usage
from model_effort_router.host.state import state_dir

from . import baseline, usage
from . import cases as corpus

MODES = baseline.MODES
DEFAULT_TIMEOUT_S = 1200.0
DEFAULT_SESSIONS = os.path.join(os.path.expanduser("~"), ".codex", "sessions")  # read only under --live


def build_command(prompt, workdir, model=None, effort=None):
    cmd = ["codex", "exec", "--json", "--skip-git-repo-check", "-s", "workspace-write"]
    if model:
        cmd += ["-m", model]
    if effort:
        cmd += ["-c", f"model_reasoning_effort={effort}"]
    return cmd + ["-c", f'projects."{workdir}".trust_level="trusted"', prompt]


def build_env(mode, state_dir, base):
    env = {**base, "MER_STATE_DIR": state_dir}
    if mode == "baseline":
        env["MER_CLASSIFIER"] = "1"  # spec-documented guard: Router hooks no-op
    return env


def default_gate(cwd):
    from model_effort_router.gate.run import load_gate_checks, run_gate
    return run_gate(cwd, load_gate_checks(cwd, os.environ), 300)["overall"]


BANNER = """\
LIVE RUN: this executes `codex exec` and consumes subscription usage.
Preconditions (yours, this tool does not do them):
  - For router runs the plugin must be installed and its hooks trusted by you beforehand. Untrusted hooks are
    skipped and the "router" run silently becomes a second baseline (such runs get router_active=false and are
    excluded from the report).
  - If the plugin is installed globally, baseline runs may still route; they are then marked contaminated.
  - Codex persists one trust_level entry for the eval workdir ({workdir}) in ~/.codex/config.toml.
"""


def read_events(path):
    """All parseable events of one route-log file; a missing file is an empty log, bad lines are skipped."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict):
            out.append(ev)
    return out


MARKER = ".mer-eval-workdir"


class WorkdirError(ValueError):
    """The eval workdir is unsafe to delete/reset; nothing was touched."""


def _inside(path, parent):
    return path == parent or path.startswith(parent.rstrip(os.sep) + os.sep)


def check_workdir(workdir, fixture):
    """Refuse (WorkdirError) unless the workdir is absent or was created by this tool. Deletes nothing."""
    real, fix = os.path.realpath(workdir), os.path.realpath(fixture)
    if real == os.path.dirname(real):
        raise WorkdirError(f"refusing the filesystem root as eval workdir: {real}")
    if _inside(real, fix) or _inside(fix, real):
        raise WorkdirError(f"eval workdir {real} equals, is inside, or contains the fixture {fix}")
    for label, guarded in (("current directory", os.path.realpath(os.getcwd())),
                           ("home directory", os.path.realpath(os.path.expanduser("~")))):
        if _inside(guarded, real):  # the workdir is that directory or one of its ancestors
            raise WorkdirError(f"eval workdir {real} is or contains the {label} ({guarded})")
    if os.path.lexists(real) and not os.path.exists(os.path.join(real, MARKER)):
        raise WorkdirError(f"eval workdir {real} exists without the {MARKER} marker this tool writes; "
                           "pick a new path or remove it yourself (nothing was deleted)")
    return real


def _clear_contents(real):
    if not os.path.isdir(real):
        return
    for name in os.listdir(real):
        if name == MARKER:
            continue
        path = os.path.join(real, name)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            os.unlink(path)


def default_workdir():
    return os.path.join(state_dir(os.environ), "eval-workdir")


def _classifier_usage(events):
    """(summed usage or None, complete?) from route events. Key absent = no model call (0 by design);
    explicit null = a model was called but its usage unknown (incomplete). Never estimated."""
    logged = [e["classifier_usage"] for e in events if e.get("event") == "route" and "classifier_usage" in e]
    measured = [u for u in logged if isinstance(u, dict)]
    return (usage.normalize(sum_usage(measured)) if measured else None), len(measured) == len(logged)


def _outcome(events):
    fixes = [e["fix_count"] for e in events if e.get("event") == "stage_spawn" and "fix_count" in e]
    reviews = [e for e in events if e.get("event") == "review"]
    last = reviews[-1] if reviews else {}
    return (max(fixes) if fixes else 0), last.get("verdict"), last.get("findings")


def _error_record(case, mode, exc, wall):
    agg = usage.aggregate(None, [])
    agg["incomplete_reasons"] = ["run_error"]
    return {"case_id": case["id"], "mode": mode, "gate_overall": "incomplete", "review_verdict": None,
            "review_findings": None, "fix_rounds": 0, "requirements_met": None, "usage": agg,
            "wall_s": round(wall, 3), "error": f"{type(exc).__name__}: {exc}"[:300],
            **({"router_active": False} if mode == "router" else {"contaminated": False})}


def run_case(case, mode, fixture, *, workdir=None, runner=default_runner, sessions_dir=DEFAULT_SESSIONS,
             gate_fn=default_gate, model=None, effort=None, timeout_s=DEFAULT_TIMEOUT_S, clock=time.monotonic,
             base_env=None):
    """One run in the fixed eval workdir. Per-case failures become a record with `error`, never an exception."""
    repo = check_workdir(workdir or default_workdir(), fixture)  # realpath: Codex trusts the resolved path
    state = tempfile.mkdtemp(prefix="mer-eval-state-")
    t0, started = clock(), time.time()
    try:
        os.makedirs(repo, exist_ok=True)
        open(os.path.join(repo, MARKER), "a").close()
        _clear_contents(repo)
        shutil.copytree(fixture, repo, dirs_exist_ok=True)
        if mode == "baseline":
            shutil.rmtree(os.path.join(repo, ".codex"), ignore_errors=True)
        env = build_env(mode, state, os.environ if base_env is None else base_env)
        stdout = runner(build_command(case["task"], repo, model, effort), stdin=subprocess.DEVNULL, env=env,
                        timeout_s=timeout_s, cwd=repo)
        wall = clock() - t0
        gate = gate_fn(repo)
        events = [e for p in sorted(glob.glob(os.path.join(state, "*.log.jsonl"))) for e in read_events(p)]
        thread_id, _ = usage.exec_stream_usage(stdout)
        rollouts = usage.find_rollouts(sessions_dir, thread_id, since_mtime=started) if thread_id else []
    except Exception as exc:  # timeout, crash, bad fixture: record it and let the batch continue
        return _error_record(case, mode, exc, clock() - t0)
    finally:
        _clear_contents(repo)
        shutil.rmtree(state, ignore_errors=True)
    routes = [e for e in events if e.get("event") == "route"]
    classifier, complete = _classifier_usage(events) if mode == "router" else (None, True)
    agg = usage.aggregate(stdout, rollouts, classifier)
    agg["incomplete_reasons"] = [] if complete else ["classifier_usage_missing"]
    fixes, verdict, findings = _outcome(events) if mode == "router" else (0, None, None)
    rec = {"case_id": case["id"], "mode": mode, "gate_overall": gate, "review_verdict": verdict,
           "review_findings": findings, "fix_rounds": fixes, "requirements_met": None, "usage": agg,
           "wall_s": round(wall, 3)}
    if mode == "router":
        rec["router_active"] = bool(routes) and any(e.get("event") == "stage_spawn" for e in events)
    else:
        mer_children = any(usage.stage_of(usage.read_rollout(p)["agent_path"]) != "other" for p in rollouts)
        rec["contaminated"] = bool(routes) or mer_children
    return rec


def main(argv=None, *, runner=default_runner, sessions_dir=DEFAULT_SESSIONS, gate_fn=default_gate):
    ap = argparse.ArgumentParser(prog="evaluation.live_runner", description=__doc__.split("\n")[0])
    ap.add_argument("--cases", required=True, help="corpus JSONL; adjudicated target=route cases are run")
    ap.add_argument("--fixture", required=True, help="fixture repo directory (copied per run)")
    ap.add_argument("--out", required=True, help="run records JSONL (appended)")
    ap.add_argument("--model")
    ap.add_argument("--effort")
    ap.add_argument("--workdir", help="fixed eval workdir, reset between runs (default: <state dir>/eval-workdir)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    ap.add_argument("--live", action="store_true", help="actually run codex exec (consumes subscription usage)")
    args = ap.parse_args(argv)
    try:
        rows = [r for r in corpus.adjudicated(corpus.load(args.cases)) if r["final"]["target"] == "route"]
    except (corpus.CorpusError, OSError) as exc:
        print(f"invalid corpus: {exc}", file=sys.stderr)
        return 1
    rows = rows[: args.limit] if args.limit is not None else rows
    if not rows or not os.path.isdir(args.fixture):
        print("nothing to run: need adjudicated route cases (and --limit > 0) and an existing --fixture dir",
              file=sys.stderr)
        return 1
    workdir = args.workdir or default_workdir()
    try:
        real_workdir = check_workdir(workdir, args.fixture)
    except WorkdirError as exc:
        print(f"unsafe workdir: {exc}", file=sys.stderr)
        return 1
    if not args.live:
        print(f"dry-run: {len(rows)} cases x {len(MODES)} modes = {len(rows) * len(MODES)} `codex exec` runs "
              "(pass --live to execute; this consumes subscription usage)")
        for r in rows:
            for mode in MODES:
                print(mode, r["id"], build_command(r["task"], real_workdir, args.model, args.effort))
        return 0
    print(BANNER.format(workdir=real_workdir), file=sys.stderr)
    with open(args.out, "a", encoding="utf-8") as out:
        for r in rows:
            for mode in MODES:
                rec = run_case(r, mode, args.fixture, workdir=workdir, runner=runner, sessions_dir=sessions_dir, gate_fn=gate_fn,
                               model=args.model, effort=args.effort, timeout_s=args.timeout)
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())

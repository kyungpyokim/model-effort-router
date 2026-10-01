"""Live Baseline-vs-Router runner (spec 22.3). Executes `codex exec` -> CONSUMES SUBSCRIPTION USAGE.

Only runs with --live; without it, prints the commands it would run (dry-run). Tests inject a fake runner.
Every run works in ONE fixed eval workdir (default: <state dir>/eval-workdir, realpath'd), reset from the fixture
before and cleared after each run; the fixture itself is never modified. Codex persists one `trust_level` entry
for that path in ~/.codex/config.toml.
Baseline = one `codex exec` (--baseline-model/-effort, MER_CLASSIFIER=1 so installed plugin hooks no-op, `.codex/`
removed); a baseline run that still shows router activity is marked `contaminated`.
Router = the `mer` CLI (model_effort_router.cli run), which classifies, runs the session, gates, escalates and
reviews itself; a router run whose mer log lacks a `route` and a `session_start` event gets router_active=false.
Every workdir is made a git repo (fixed identity, one fixture commit) before the run; afterwards `git diff` and the
untracked list go to <out dir>/<case>.<mode>.diff so a human can judge requirements_met.
Usage: python3 -m evaluation.live_runner --cases CORPUS --fixture DIR --out RUNS.jsonl [--model M] [--effort E] [--baseline-model/-effort] [--limit N] [--live]
"""
import argparse
import glob
import json
import os
import re
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
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TIMEOUT_S = 1200.0  # per codex call
MER_CALL_BUDGET = 5  # codex calls in one mer run: implement + 2 escalations + review + re-review
MER_GATE_BUDGET_S = 3 * 4 * 300  # up to 3 gate runs x 4 check kinds x mer's 300 s per check
MER_GRACE_S = 15  # SIGTERM -> SIGKILL: mer needs time to stop its own codex call (5 s grace) first
DEFAULT_SESSIONS = os.path.join(os.path.expanduser("~"), ".codex", "sessions")  # read only under --live


def build_command(prompt, workdir, model=None, effort=None):
    cmd = ["codex", "exec", "--json", "--skip-git-repo-check", "-s", "workspace-write"]
    if model:
        cmd += ["-m", model]
    if effort:
        cmd += ["-c", f"model_reasoning_effort={effort}"]
    return cmd + ["-c", f'projects."{workdir}".trust_level="trusted"', prompt]


def build_mer_command(task, workdir, call_timeout_s=DEFAULT_TIMEOUT_S):
    return [sys.executable, "-m", "model_effort_router.cli", "run", "--cwd", workdir, "--json", "--exit-zero",
            "--timeout", f"{call_timeout_s:g}", task]


def build_env(mode, state_dir, base):
    env = {**base, "MER_STATE_DIR": state_dir}
    if mode == "baseline":
        env["MER_CLASSIFIER"] = "1"  # spec-documented guard: Router hooks no-op
    else:  # mer sets the guard itself for the codex sessions it starts; it must find this checkout's package
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [REPO_ROOT, base.get("PYTHONPATH")]))
    return env


GIT_ID = ["-c", "user.name=mer-eval", "-c", "user.email=mer-eval@example.invalid", "-c", "commit.gpgsign=false",
          "-c", "core.hooksPath=/dev/null", "-c", "init.templateDir="]


def _git(repo, *args):
    """Pinned to <repo>/.git: if a run deletes it, git fails instead of falling through to an enclosing repo."""
    pin = [f"--git-dir={os.path.join(repo, '.git')}", f"--work-tree={repo}"]
    return subprocess.run(["git", *pin, *GIT_ID, *args], cwd=repo, check=True, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=120).stdout


def _enclosing_git(path):
    parent = os.path.dirname(path)
    while parent != os.path.dirname(parent):
        if os.path.lexists(os.path.join(parent, ".git")):
            return parent
        parent = os.path.dirname(parent)
    return None


def init_git_repo(repo):
    """git init + one fixture commit, only inside the (already validated) eval workdir."""
    _git(repo, "init", "-q")
    os.makedirs(os.path.join(repo, ".git", "info"), exist_ok=True)  # absent without a template dir
    with open(os.path.join(repo, ".git", "info", "exclude"), "a") as f:
        f.write(MARKER + "\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "fixture")


def save_diff(repo, path):
    """Everything the run changed vs the fixture commit (new files included) plus the untracked list."""
    untracked = _git(repo, "ls-files", "--others", "--exclude-standard").splitlines()
    _git(repo, "add", "-A")
    header = "".join(f"# untracked: {name}\n" for name in untracked)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + _git(repo, "diff", "--cached"))
    return path


def default_gate(cwd):
    from model_effort_router.gate.run import load_gate_checks, run_gate
    return run_gate(cwd, load_gate_checks(cwd, os.environ), 300)["overall"]


BANNER = """\
LIVE RUN: this executes `codex exec` (baseline directly, router through the `mer` CLI) and consumes subscription usage.
Preconditions (yours, this tool does not do them):
  - Router runs need no plugin: mer starts its codex sessions with MER_CLASSIFIER=1 so hooks of an installed plugin
    no-op inside them. If the plugin is installed globally, baseline runs may still route; they are then marked
    contaminated.
  - Codex persists one trust_level entry for the eval workdir ({workdir}) in ~/.codex/config.toml.
  - The workdir is turned into a git repo (fixed identity, one commit); diffs are saved next to --out.
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
    repo = _enclosing_git(real)
    if repo:  # mer's review diff would fall through to that repository if the run broke the workdir's .git
        raise WorkdirError(f"eval workdir {real} is inside the git work tree {repo}; pick a path outside it")
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
    """(escalations, last review verdict, findings) from the mer log."""
    escalations = sum(e.get("event") == "escalate" for e in events)
    reviews = [e for e in events if e.get("event") == "review"]
    last = reviews[-1] if reviews else {}
    return escalations, last.get("verdict"), last.get("findings")


def _error_record(case, mode, exc, wall, model=None, effort=None):
    agg = usage.aggregate(None, [])
    agg["incomplete_reasons"] = ["run_error"]
    return {"case_id": case["id"], "mode": mode, "gate_overall": "incomplete", "review_verdict": None,
            "review_findings": None, "fix_rounds": 0, "requirements_met": None, "usage": agg,
            "wall_s": round(wall, 3), "model": model, "effort": effort, "diff_path": None,
            "error": f"{type(exc).__name__}: {exc}"[:300],
            **({"router_active": False} if mode == "router" else {"contaminated": False})}


def _parse_mer(stdout):
    lines = [l for l in stdout.splitlines() if l.strip()]
    result = json.loads(lines[-1]) if lines else None
    if not isinstance(result, dict) or "calls" not in result:
        raise ValueError("mer printed no JSON result")
    return result


def _mer_thread_usage(mer, covered):
    """Usage mer reported (per-call deltas, summed per thread) for threads without a rollout on disk."""
    total = usage.normalize(None)
    for call in mer.get("calls", []):
        if call.get("thread_id") not in covered and call.get("usage"):
            total = usage.add(total, usage.normalize({k: call["usage"].get(short) for k, short in usage.KEYS.items()}))
    return total


def run_case(case, mode, fixture, *, workdir=None, runner=default_runner, sessions_dir=DEFAULT_SESSIONS,
             gate_fn=default_gate, model=None, effort=None, timeout_s=DEFAULT_TIMEOUT_S, clock=time.monotonic,
             base_env=None, out_dir=None):
    """One run in the fixed eval workdir. Per-case failures become a record with `error`, never an exception."""
    repo = check_workdir(workdir or default_workdir(), fixture)  # realpath: Codex trusts the resolved path
    state = tempfile.mkdtemp(prefix="mer-eval-state-")
    t0, started = clock(), time.time()
    mer, diff_path, diff_error = None, None, None
    try:
        os.makedirs(repo, exist_ok=True)
        open(os.path.join(repo, MARKER), "a").close()
        _clear_contents(repo)
        shutil.copytree(fixture, repo, dirs_exist_ok=True)
        if mode == "baseline":
            shutil.rmtree(os.path.join(repo, ".codex"), ignore_errors=True)
        init_git_repo(repo)
        env = build_env(mode, state, os.environ if base_env is None else base_env)
        if mode == "router":
            cmd, extra = build_mer_command(case["task"], repo, timeout_s), {"grace_s": MER_GRACE_S}
            outer_s = timeout_s * MER_CALL_BUDGET + MER_GATE_BUDGET_S
        else:
            cmd, extra, outer_s = build_command(case["task"], repo, model, effort), {}, timeout_s
        stdout = runner(cmd, stdin=subprocess.DEVNULL, env=env, timeout_s=outer_s, cwd=repo, **extra)
        wall = clock() - t0
        gate = gate_fn(repo)
        if out_dir:
            try:
                diff_path = save_diff(repo, os.path.join(out_dir, f"{re.sub(r'[^A-Za-z0-9._-]', '_', case['id'])}.{mode}.diff"))
            except (OSError, subprocess.SubprocessError) as exc:
                diff_error = type(exc).__name__
        events = [e for p in sorted(glob.glob(os.path.join(state, "*.log.jsonl"))) for e in read_events(p)]
        if mode == "router":
            mer = _parse_mer(stdout)
            threads = [t for t in mer.get("threads", []) if t]
        else:
            thread_id, _ = usage.exec_stream_usage(stdout)
            threads = [thread_id] if thread_id else []
        rollouts = usage.find_rollouts(sessions_dir, threads, since_mtime=started) if threads else []
    except Exception as exc:  # timeout, crash, bad fixture: record it and let the batch continue
        return _error_record(case, mode, exc, clock() - t0, model, effort)
    finally:
        _clear_contents(repo)
        shutil.rmtree(state, ignore_errors=True)
    routes = [e for e in events if e.get("event") == "route"]
    classifier, complete = _classifier_usage(events) if mode == "router" else (None, True)
    if mode == "router":  # mer's sessions are root sessions (review ones separate): rollouts per reported thread
        # a rollout without token_count does not cover its thread: fall back to what mer reported
        covered = {r["session_id"] for r in map(usage.read_rollout, rollouts) if r["usage"] is not None}
        agg = usage.aggregate(None, rollouts, classifier, extra_main=_mer_thread_usage(mer, covered))
    else:
        agg = usage.aggregate(stdout, rollouts, classifier)
    agg["incomplete_reasons"] = [] if complete else ["classifier_usage_missing"]
    escalations, verdict, findings = _outcome(events) if mode == "router" else (0, None, None)
    rec = {"case_id": case["id"], "mode": mode, "gate_overall": gate, "review_verdict": verdict,
           "review_findings": findings, "fix_rounds": escalations, "requirements_met": None, "usage": agg,
           "wall_s": round(wall, 3), "model": model, "effort": effort, "thread_ids": threads,
           "diff_path": diff_path}
    if diff_error:
        rec["diff_error"] = diff_error
    if mode == "router":
        profile = mer.get("profile") or {}
        rec.update(router_active=bool(routes) and any(e.get("event") == "session_start" for e in events),
                   level=mer.get("level"), session_profile=mer.get("profile"), final_profile=mer.get("final_profile"),
                   escalations=escalations, mer_status=mer.get("status"),
                   model=profile.get("model"), effort=profile.get("applied_effort"))
    else:
        mer_children = any(usage.stage_of(usage.read_rollout(p)["agent_path"]) != "other" for p in rollouts)
        rec["contaminated"] = bool(routes) or mer_children
    return rec


def main(argv=None, *, runner=default_runner, sessions_dir=DEFAULT_SESSIONS, gate_fn=default_gate):
    ap = argparse.ArgumentParser(prog="evaluation.live_runner", description=__doc__.split("\n")[0])
    ap.add_argument("--cases", required=True, help="corpus JSONL; adjudicated or pilot target=route cases are run")
    ap.add_argument("--fixture", required=True, help="fixture repo directory (copied per run)")
    ap.add_argument("--out", required=True, help="run records JSONL (appended)")
    ap.add_argument("--model", help="baseline model (router mode: mer picks its own profiles)")
    ap.add_argument("--effort", help="baseline effort")
    ap.add_argument("--baseline-model")
    ap.add_argument("--baseline-effort")
    ap.add_argument("--workdir", help="fixed eval workdir, reset between runs (default: <state dir>/eval-workdir)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    ap.add_argument("--live", action="store_true", help="actually run codex exec (consumes subscription usage)")
    args = ap.parse_args(argv)
    try:
        rows = [r for r in corpus.runnable(corpus.load(args.cases)) if r["final"]["target"] == "route"]
    except (corpus.CorpusError, OSError) as exc:
        print(f"invalid corpus: {exc}", file=sys.stderr)
        return 1
    rows = rows[: args.limit] if args.limit is not None else rows
    if not rows or not os.path.isdir(args.fixture):
        print("nothing to run: need adjudicated or pilot route cases (and --limit > 0) and an existing --fixture dir",
              file=sys.stderr)
        return 1
    settings = {"baseline": (args.baseline_model or args.model, args.baseline_effort or args.effort),
                "router": (None, None)}
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
                print(mode, r["id"], build_mer_command(r["task"], real_workdir) if mode == "router"
                      else build_command(r["task"], real_workdir, *settings[mode]))
        return 0
    print(BANNER.format(workdir=real_workdir), file=sys.stderr)
    out_dir = os.path.dirname(os.path.abspath(args.out))
    with open(args.out, "a", encoding="utf-8") as out:
        for r in rows:
            for mode in MODES:
                rec = run_case(r, mode, args.fixture, workdir=workdir, runner=runner, sessions_dir=sessions_dir, gate_fn=gate_fn,
                               model=settings[mode][0], effort=settings[mode][1], timeout_s=args.timeout,
                               out_dir=out_dir)
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())

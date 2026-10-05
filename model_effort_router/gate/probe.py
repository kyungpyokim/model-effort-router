"""Test-without-change probe: do the tests this run added or changed also pass on the pre-change code?

Runs the gate's own test command on a temp snapshot (HEAD + this run's test files). Reports only; the user's
working tree and .git are never written, and the probe never raises.
"""
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
from pathlib import PurePosixPath

from ..review import PROBE_TAIL_MAX, _git
from .run import run_check

_JS_EXTS = {"js", "jsx", "ts", "tsx", "mjs", "cjs"}
_CODE_EXTS = _JS_EXTS | {"py", "go", "rb"}
_TEST_DIRS = {"tests", "test", "spec", "__tests__", "testdata", "fixtures", "__snapshots__"}
OUTPUT_TAIL_CHARS = PROBE_TAIL_MAX  # of the first run's output, so a human can tell an assertion from an ImportError
_HAS_DATA_FILTER = hasattr(tarfile, "data_filter")


def is_test_path(path):
    """Path rules only (never reads content); conservative, a missed test only means 'skipped'."""
    p = PurePosixPath(path)
    dirs, stem, ext = set(p.parts[:-1]), p.stem, p.suffix.lstrip(".")
    if p.name == "conftest.py" or dirs & {"fixtures", "testdata"}:
        return False  # helpers are test-side (see is_test_side) but not what decides whether to probe
    if ext == "py":
        return stem.startswith("test_") or stem.endswith("_test") or "tests" in dirs
    if ext in _JS_EXTS:
        return stem.endswith((".test", ".spec")) or "__tests__" in dirs
    if ext == "go":
        return stem.endswith("_test")
    if ext == "rb":
        return stem.endswith("_spec") or bool(dirs & {"spec", "test"})
    return False


def is_test_side(path):
    """Changed by the run on the test side (tests, helpers, data): goes over the snapshot. Only product source stays at HEAD.
    Code counts only under tests/ or __tests__/: a bare spec/, test/ or fixtures/ dir may hold product code (app/spec/schema.py)."""
    p = PurePosixPath(path)
    dirs = set(p.parts[:-1])
    if is_test_path(path) or p.name == "conftest.py":
        return True
    if p.suffix.lstrip(".") in _CODE_EXTS:
        return bool(dirs & {"tests", "__tests__"})
    return bool(dirs & _TEST_DIRS)  # data, snapshots, golden files


def result(verdict, reason=None, overlay=(), duration_s=0.0, output_tail=None):
    """`overlay`: every path laid over the snapshot; `tests`: the test files among them."""
    out = {"verdict": verdict, "reason": reason, "tests": [p for p in overlay if is_test_path(p)],
           "overlay": list(overlay), "duration_s": duration_s}
    if output_tail:
        out["output_tail"] = output_tail[-OUTPUT_TAIL_CHARS:]
    return out


def _extract_tar(fileobj, dest):
    with tarfile.open(fileobj=fileobj, mode="r|") as tar:
        for member in tar:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts:
                raise ValueError(f"unsafe path in archive: {member.name}")
            if _HAS_DATA_FILTER:
                tar.extract(member, dest, filter="data")
            elif member.isfile() or member.isdir():  # no data filter: refuse links and special files outright
                tar.extract(member, dest)
            else:
                raise ValueError(f"unsupported archive member: {member.name}")


def _extract_head(cwd, dest):
    proc = subprocess.Popen(["git", "archive", "--format=tar", "HEAD"], cwd=cwd, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        _extract_tar(proc.stdout, dest)
        proc.stdout.read()  # the tar end marker is not consumed; drain so git does not die on a closed pipe
    except BaseException:
        proc.kill()
        raise
    finally:
        proc.stdout.close()
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("git archive HEAD failed")


def _overlay_tests(cwd, dest, paths):
    """Put this run's test files over the snapshot (a test deleted in the working tree is deleted there too)."""
    root = os.path.realpath(dest)
    for rel in paths:
        src, dst = os.path.join(cwd, rel), os.path.join(dest, rel)
        parent = os.path.realpath(os.path.dirname(dst))
        if parent != root and not parent.startswith(root + os.sep):
            raise ValueError(f"path escapes the snapshot: {rel}")
        if os.path.islink(src):
            raise ValueError(f"test file is a symlink: {rel}")
        if os.path.lexists(dst):
            os.remove(dst)  # also a symlink from HEAD: never write through it
        if os.path.isfile(src):
            os.makedirs(parent, exist_ok=True)
            shutil.copy2(src, dst)


def _unsupported(cwd):
    """Why the probe cannot snapshot this directory (None: it can)."""
    rc, top = _git(["rev-parse", "--show-toplevel"], cwd)
    if rc != 0:
        return "not a git repository"
    if os.path.realpath(top.strip()) != os.path.realpath(cwd):
        return "cwd is not the repository root"  # git archive and diff paths would disagree
    if _git(["rev-parse", "--verify", "-q", "HEAD"], cwd)[0] != 0:
        return "no HEAD commit"
    return None


def _run_in_snapshot(cwd, overlay, check, timeout_s, run):
    with tempfile.TemporaryDirectory(prefix="mer-probe-") as snap:  # removed on every path
        _extract_head(cwd, snap)
        _overlay_tests(cwd, snap, overlay)
        return run(check, snap, timeout_s)


def _probe(cwd, changed_paths, overlay, check, timeout_s, run):
    if not any(is_test_path(p) for p in changed_paths):
        return result("skipped", "no test files changed")
    if all(is_test_side(p) or p.endswith(".md") for p in changed_paths):  # docs are neutral
        return result("skipped", "only tests changed", overlay)  # nothing at HEAD could differ
    if check is None:
        return result("skipped", "no test command", overlay)
    reason = _unsupported(cwd)
    if reason:
        return result("skipped", reason, overlay)
    first = _run_in_snapshot(cwd, overlay, check, timeout_s, run)
    if first["status"] == "passed":
        return result("passes_without_change", overlay=overlay)
    if first.get("reason"):  # timeout or could not start: not a real test failure
        return result("inconclusive", f"the test command did not finish: {first['reason']}", overlay,
                      output_tail=first.get("output_tail"))
    # the snapshot has no ignored files (.venv, node_modules): a failure only counts when plain HEAD passes
    if _run_in_snapshot(cwd, [], check, timeout_s, run)["status"] != "passed":
        return result("inconclusive", "the test command also fails on the unchanged pre-change code", overlay,
                      output_tail=first.get("output_tail"))
    return result("fails_without_change", overlay=overlay, output_tail=first.get("output_tail"))


def probe_without_change(cwd, changed_paths, test_check, timeout_s, run=run_check):
    """{"verdict", "reason", "tests", "overlay", "duration_s"[, "output_tail"]}; never raises."""
    t0 = time.monotonic()
    overlay = []
    try:
        overlay = sorted({p for p in changed_paths if is_test_side(p)})
        out = _probe(cwd, changed_paths, overlay, test_check, timeout_s, run)
    except Exception as exc:  # a broken probe must not break the run
        out = result("inconclusive", f"{type(exc).__name__}: {exc}"[:300], overlay)
    return {**out, "duration_s": round(time.monotonic() - t0, 2)}

"""Lifecycle helpers for the two-stage route plan directories.

router.route() creates a plan directory for every two-stage route and hands it to the caller,
which either runs the chain against that artifact or discards it. Callers that never use it —
the eval and test harnesses route hundreds of cases per run — must discard it themselves:
leaked directories accumulated into the tens of thousands until an 8-hex name collided and
routing crashed on a directory that already existed.

Ownership stays on the caller's side deliberately: production keeps the plan dir until the
chain runs (or `--cleanup-plan-dir` removes it), so the router must not clean up after itself.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import router


def discard_plan_dir(plan_dir: str | None) -> bool:
    """Remove one plan directory this router created; never anything else.

    Ownership is proved by router.router_plan_file, the same guard the CLI uses, so a
    directory that lacks the router marker, sits outside the temp dir, or hides behind a
    symlink is kept. Returns whether a directory was removed.
    """
    if not plan_dir:
        return False
    try:
        plan_file = router.router_plan_file(str(Path(plan_dir) / "plan.json"))
    except ValueError:
        return False
    shutil.rmtree(plan_file.parent, ignore_errors=True)
    return not plan_file.parent.exists()


def router_plan_dirs() -> set[str]:
    """Names of the router-owned plan directories currently in the temp dir."""
    temp_dir = Path(tempfile.gettempdir()).resolve()
    try:
        entries = list(temp_dir.iterdir())
    except OSError:
        return set()
    return {
        entry.name
        for entry in entries
        if entry.is_dir() and not entry.is_symlink() and router.ROUTER_PLAN_DIR_RE.fullmatch(entry.name)
    }


def sweep_plan_dirs(keep: set[str]) -> list[str]:
    """Remove the router-owned plan dirs created since ``keep`` (a before-snapshot).

    For harnesses that route in a subprocess and cannot hand the plan dir back to
    discard_plan_dir: a directory that existed before the run, and any directory without the
    router marker, is never touched. Returns the names it removed.
    """
    temp_dir = Path(tempfile.gettempdir()).resolve()
    removed = []
    for name in sorted(router_plan_dirs() - set(keep)):
        if discard_plan_dir(str(temp_dir / name)):
            removed.append(name)
    return removed

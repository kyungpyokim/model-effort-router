"""Test-session guard for the router's two-stage plan directories.

router.route() creates a plan directory for every two-stage route and hands it to the caller,
which either runs the chain against that artifact or discards it. Tests route thousands of times
and never run the chain, so leaked directories accumulated until an 8-hex name collided and
routing crashed. This fixture discards exactly the directories a test created — after it ends,
on failure and on error alike — and never touches any other directory.

Every module that execs scripts/router.py through importlib now reuses an already-loaded copy
from the same file, so sys.modules holds a single router instance for the whole run; the guard
still wraps every instance it finds, in case a future loader registers another one.
"""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import plan_dirs  # noqa: E402
import router  # noqa: E402

ROUTER_PATH = str(ROOT / "scripts" / "router.py")


def _router_instances() -> list:
    """Every loaded module whose file is scripts/router.py, deduplicated."""
    instances = {id(router): router, id(plan_dirs.router): plan_dirs.router}
    for module in list(sys.modules.values()):
        if module is not None and getattr(module, "__file__", None) == ROUTER_PATH:
            instances[id(module)] = module
    return list(instances.values())


@pytest.fixture(autouse=True)
def _discard_route_plan_dirs(monkeypatch):
    created: list[str] = []

    for instance in _router_instances():
        original_route = instance.route

        def route_and_track(*args, _original=original_route, **kwargs):
            result = _original(*args, **kwargs)
            plan_dir = getattr(result, "plan_dir", None)
            if plan_dir:
                created.append(plan_dir)
            return result

        monkeypatch.setattr(instance, "route", route_and_track)

    try:
        yield
    finally:
        for plan_dir in created:
            plan_dirs.discard_plan_dir(plan_dir)

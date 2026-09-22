from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import plan_dirs  # noqa: E402
import router  # noqa: E402

CONFIG = router.load_config(ROOT / "config" / "model-map.json")

# The success path of the conftest guard is observed across two tests in PlanDirGuardTests.
LEAKED_BY_GUARD_TEST: list[Path] = []

GUARD_PROBE = '''\
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import router

CONFIG = router.load_config(ROOT / "config" / "model-map.json")


def test_probe_leaks_a_plan_dir_then_errors():
    result = router.route("guard probe", "codex", CONFIG, "L5", "implementation")
    Path(os.environ["GUARD_PROBE_RECORD"]).write_text(result.plan_dir or "", encoding="utf-8")
    raise RuntimeError("deliberate failure after creating a plan dir")
'''


def routed_plan_dir() -> Path:
    """Route a two-stage case (L5 implementation) and return the plan dir it created."""
    result = router.route("cleanup harness regression task", "codex", CONFIG, "L5", "implementation")
    assert result.plan_dir, "expected a two-stage route with a plan dir"
    return Path(result.plan_dir)


def free_plan_dir_name() -> Path:
    """Create and return an empty directory whose name is a valid router plan dir name."""
    temp_dir = Path(tempfile.gettempdir()).resolve()
    while True:
        path = temp_dir / f"codex-route-{uuid.uuid4().hex[:8]}"
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            continue
        return path


class PlanDirDiscardTests(unittest.TestCase):
    def test_discard_removes_the_directory_the_router_created(self):
        plan_dir = routed_plan_dir()
        self.assertTrue(plan_dir.is_dir())

        self.assertTrue(plan_dirs.discard_plan_dir(str(plan_dir)))
        self.assertFalse(plan_dir.exists())

    def test_discard_is_idempotent_and_handles_missing_input(self):
        self.assertFalse(plan_dirs.discard_plan_dir(None))
        self.assertFalse(plan_dirs.discard_plan_dir(""))

        plan_dir = routed_plan_dir()
        self.assertTrue(plan_dirs.discard_plan_dir(str(plan_dir)))
        self.assertFalse(plan_dirs.discard_plan_dir(str(plan_dir)))

    def test_discard_never_removes_a_directory_the_router_did_not_create(self):
        # Right name, no router marker: not ours.
        unmarked = free_plan_dir_name()
        self.addCleanup(shutil.rmtree, unmarked, ignore_errors=True)
        (unmarked / "plan.json").write_text("{}", encoding="utf-8")
        self.assertFalse(plan_dirs.discard_plan_dir(str(unmarked)))
        self.assertTrue(unmarked.is_dir())

        # Router marker but a name the router never generates.
        wrong_name = Path(tempfile.gettempdir()).resolve() / f"codex-route-{uuid.uuid4().hex}"
        wrong_name.mkdir(exist_ok=True)
        self.addCleanup(shutil.rmtree, wrong_name, ignore_errors=True)
        (wrong_name / router.ROUTER_PLAN_MARKER).write_text("router-owned\n", encoding="utf-8")
        self.assertFalse(plan_dirs.discard_plan_dir(str(wrong_name)))
        self.assertTrue(wrong_name.is_dir())

        # Marker and name right, but nested outside the temp dir the router uses.
        nested_root = Path(tempfile.mkdtemp(prefix="plan-dir-nested-"))
        self.addCleanup(shutil.rmtree, nested_root, ignore_errors=True)
        nested = nested_root / "codex-route-00000000"
        nested.mkdir()
        (nested / router.ROUTER_PLAN_MARKER).write_text("router-owned\n", encoding="utf-8")
        self.assertFalse(plan_dirs.discard_plan_dir(str(nested)))
        self.assertTrue(nested.is_dir())


    def test_sweep_removes_only_the_dirs_created_since_the_snapshot(self):
        kept = routed_plan_dir()
        self.addCleanup(plan_dirs.discard_plan_dir, str(kept))
        snapshot = plan_dirs.router_plan_dirs()
        self.assertIn(kept.name, snapshot)

        fresh = routed_plan_dir()
        foreign = free_plan_dir_name()
        self.addCleanup(shutil.rmtree, foreign, ignore_errors=True)

        removed = plan_dirs.sweep_plan_dirs(snapshot)

        self.assertIn(fresh.name, removed)
        self.assertFalse(fresh.exists())
        self.assertTrue(kept.exists())
        self.assertTrue(foreign.is_dir())


class PlanDirGuardTests(unittest.TestCase):
    """The conftest autouse guard must discard plan dirs a test created, on success and on error."""

    def test_a_a_test_may_leak_a_plan_dir(self):
        plan_dir = routed_plan_dir()
        LEAKED_BY_GUARD_TEST.append(plan_dir)
        self.assertTrue(plan_dir.is_dir())

    def test_b_the_previous_test_leaked_nothing(self):
        self.assertEqual(len(LEAKED_BY_GUARD_TEST), 1)
        self.assertFalse(LEAKED_BY_GUARD_TEST[0].exists())

    def test_c_the_guard_discards_a_plan_dir_when_the_test_errors(self):
        # An erroring test is exactly the case a leaked directory would survive, so run a probe
        # in a nested pytest process that leaks a plan dir and then fails, and assert the guard
        # removed it anyway.
        probe = ROOT / "tests" / "test_guard_probe_tmp.py"
        probe.write_text(GUARD_PROBE, encoding="utf-8")
        self.addCleanup(probe.unlink, True)

        record_dir = Path(tempfile.mkdtemp(prefix="guard-probe-"))
        self.addCleanup(shutil.rmtree, record_dir, ignore_errors=True)
        record = record_dir / "leaked_plan_dir.txt"
        env = {
            **os.environ,
            "PYTHONPATH": str(ROOT / "scripts"),
            "GUARD_PROBE_RECORD": str(record),
        }
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", str(probe), "-q", "-p", "no:cacheprovider"],
            capture_output=True, text=True, cwd=ROOT, env=env,
        )
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertTrue(record.is_file(), completed.stdout + completed.stderr)
        leaked = Path(record.read_text(encoding="utf-8").strip())
        self.assertTrue(router.ROUTER_PLAN_DIR_RE.fullmatch(leaked.name), leaked)
        self.assertFalse(leaked.exists(), f"plan dir of the erroring probe test leaked: {leaked}")

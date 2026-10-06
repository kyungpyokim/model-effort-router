import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.hook_helpers import ROOT

PLUGIN = ROOT / "plugins" / "antigravity-model-effort-router"


class AntigravityBundleTest(unittest.TestCase):
    def test_native_manifest_validates(self):
        manifest = json.loads((PLUGIN / "plugin.json").read_text())
        self.assertEqual(set(manifest), {"$schema", "name", "description"})
        self.assertEqual(manifest["name"], "model-effort-router")
        checked = subprocess.run(["agy", "plugin", "validate", str(PLUGIN)], capture_output=True, text=True, timeout=30)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)

    def test_bundle_routes_but_rejects_unverified_worker_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            env = {k: v for k, v in os.environ.items() if not k.startswith("MER_")}
            env.update(MER_CORE_PATH=str(ROOT), HOME=str(root), MER_STATE_DIR=str(root / "state"))
            route = subprocess.run([sys.executable, str(PLUGIN / "bin" / "mer"), "route", "--role", "fix",
                                    "--effort", "medium", "--json", "--cwd", str(root), "Fix parser.py"],
                                   capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(route.returncode, 0, route.stderr)
            self.assertEqual(json.loads(route.stdout)["role"], "fix")
            run = subprocess.run([sys.executable, str(PLUGIN / "bin" / "mer"), "run", "--role", "fix",
                                 "--effort", "medium", "--cwd", str(root), "Fix parser.py"],
                                capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(run.returncode, 2)
            self.assertIn("execution isolation is unverified", run.stderr)

    def test_bundle_has_native_skill_and_no_unsafe_hook(self):
        skill = (PLUGIN / "skills" / "classify" / "SKILL.md").read_text()
        self.assertIn("mer route", skill)
        self.assertIn("worker execution remains unsupported", skill)
        self.assertFalse((PLUGIN / "hooks.json").exists())
        self.assertTrue(os.access(PLUGIN / "bin" / "mer", os.X_OK))


if __name__ == "__main__":
    unittest.main()

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
            route = subprocess.run(
                [
                    sys.executable,
                    str(PLUGIN / "bin" / "mer"),
                    "route",
                    "--role",
                    "fix",
                    "--effort",
                    "medium",
                    "--json",
                    "--cwd",
                    str(root),
                    "Fix parser.py",
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            self.assertEqual(route.returncode, 0, route.stderr)
            self.assertEqual(json.loads(route.stdout)["role"], "fix")
            text = subprocess.run(
                [
                    sys.executable,
                    str(PLUGIN / "bin" / "mer"),
                    "route",
                    "--role",
                    "fix",
                    "--effort",
                    "medium",
                    "--cwd",
                    str(root),
                    "Fix parser.py",
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            self.assertEqual(text.returncode, 0, text.stderr)
            # The one display form everywhere: the plugin tag, then the pair with the effort shown separately.
            self.assertEqual(
                text.stdout.strip(), "[model-effort-router] fix → execution · gemini-3.8-flash · effort medium"
            )

    def test_pre_invocation_leads_with_the_tagged_pair(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            env = {k: v for k, v in os.environ.items() if not k.startswith("MER_")}
            env.update(MER_CORE_PATH=str(ROOT), HOME=str(root), MER_STATE_DIR=str(root / "state"))
            hook = subprocess.run(
                [sys.executable, str(PLUGIN / "hooks" / "pre_invocation.py")],
                input=json.dumps({"invocationNum": 0, "workspacePaths": [str(root)]}),
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                cwd=str(root),
            )
            self.assertEqual(hook.returncode, 0, hook.stderr)
            message = json.loads(hook.stdout)["injectSteps"][0]["ephemeralMessage"]
            # No role classification in this hook: the tagged model/effort pair still leads the message.
            self.assertTrue(message.startswith("[model-effort-router] gemini-3.8-flash · effort high. "), message)
            run = subprocess.run(
                [
                    sys.executable,
                    str(PLUGIN / "bin" / "mer"),
                    "run",
                    "--role",
                    "fix",
                    "--effort",
                    "medium",
                    "--cwd",
                    str(root),
                    "Fix parser.py",
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            self.assertEqual(run.returncode, 2)
            self.assertIn("execution isolation is unverified", run.stderr)

    def test_bundle_has_native_skill_and_advisory_hook(self):
        skill = (PLUGIN / "skills" / "classify" / "SKILL.md").read_text()
        self.assertIn("mer route", skill)
        self.assertIn("mer run` is unsupported on this host", skill)
        hooks = json.loads((PLUGIN / "hooks.json").read_text())["model-effort-router"]
        self.assertEqual(set(hooks), {"PreInvocation"})
        self.assertTrue(os.access(PLUGIN / "bin" / "mer", os.X_OK))


if __name__ == "__main__":
    unittest.main()

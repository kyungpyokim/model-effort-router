import io
import json
import tempfile
import unittest
from pathlib import Path

from model_effort_router.cli import main
from model_effort_router.host import codex_hooks
from model_effort_router.policy.config import resolve_config
from model_effort_router.policy.router import route
from model_effort_router.policy.targeting import NO_ROUTE


class RouterModeCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = Path(self.tmp.name)
        self.user_cfg_dir = self.cwd / "user_config"
        self.user_cfg_path = self.user_cfg_dir / "config.json"
        self.env = {
            "HOME": str(self.cwd),
            "MER_USER_CONFIG": str(self.user_cfg_path),
        }

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        out = io.StringIO()
        code = main(list(args), env=self.env, out=out)
        return code, out.getvalue()

    def test_default_status_is_on(self):
        code, out = self.run_cli("status", "--cwd", str(self.cwd))
        self.assertEqual(code, 0)
        self.assertIn("Status: ON", out)
        self.assertIn("mode: auto", out)

    def test_global_off_and_on(self):
        code, out = self.run_cli("off")
        self.assertEqual(code, 0)
        self.assertIn("Router disabled (mode: off, scope: global)", out)
        self.assertTrue(self.user_cfg_path.is_file())
        saved = json.loads(self.user_cfg_path.read_text())
        self.assertEqual(saved["router"]["mode"], "off")

        code, out = self.run_cli("status", "--cwd", str(self.cwd))
        self.assertEqual(code, 0)
        self.assertIn("Status: OFF", out)
        self.assertIn("mode: off", out)
        self.assertIn("global config.json", out)

        code, out = self.run_cli("on")
        self.assertEqual(code, 0)
        self.assertIn("Router enabled (mode: auto, scope: global)", out)
        saved = json.loads(self.user_cfg_path.read_text())
        self.assertEqual(saved["router"]["mode"], "auto")

        code, out = self.run_cli("status", "--cwd", str(self.cwd))
        self.assertEqual(code, 0)
        self.assertIn("Status: ON", out)

    def test_local_off_and_on_precedence(self):
        local_cfg = self.cwd / ".model-effort-router.json"
        code, out = self.run_cli("mode", "off", "--local", "--cwd", str(self.cwd))
        self.assertEqual(code, 0)
        self.assertIn("Router disabled (mode: off, scope: local (.model-effort-router.json))", out)
        self.assertTrue(local_cfg.is_file())
        saved = json.loads(local_cfg.read_text())
        self.assertEqual(saved["router"]["mode"], "off")

        code, out = self.run_cli("status", "--cwd", str(self.cwd))
        self.assertEqual(code, 0)
        self.assertIn("Status: OFF", out)
        self.assertIn("local .model-effort-router.json", out)

        code, out = self.run_cli("mode", "on", "--local", "--cwd", str(self.cwd))
        self.assertEqual(code, 0)
        self.assertIn("Router enabled (mode: auto, scope: local (.model-effort-router.json))", out)
        saved = json.loads(local_cfg.read_text())
        self.assertEqual(saved["router"]["mode"], "auto")

    def test_router_bypassed_when_mode_is_off(self):
        # Configure off locally
        self.run_cli("off", "--local", "--cwd", str(self.cwd))
        repo_cfg, user_cfg = codex_hooks.load_configs(str(self.cwd), self.env)
        cfg = resolve_config(repo=repo_cfg, user=user_cfg)
        self.assertEqual(cfg.mode, "off")

        plan = route("implement a new feature", repo_config=repo_cfg, user_config=user_cfg)
        self.assertEqual((plan.target, plan.mode, plan.decision), (NO_ROUTE, "off", None))

        # Check that user_prompt_submit hook immediately returns None
        payload = {"prompt": "implement a new feature", "session_id": "test-sid", "cwd": str(self.cwd)}
        res = codex_hooks.user_prompt_submit(payload, self.env, str(self.cwd))
        self.assertIsNone(res)


if __name__ == "__main__":
    unittest.main()

import json
import unittest

from tests.hook_helpers import ROOT, HookCase


class TimeoutClampTest(HookCase):
    def test_timeout_clamped_and_logged(self):
        self.write_repo_config({"difficulty": {"backend": "fake", "timeout_s": 25}})
        self.submit()
        ev = [e for e in self.log_events() if e["event"] == "route"][0]
        self.assertTrue(ev["timeout_clamped"])
        self.assertEqual(ev["decision"]["reason_codes"], ["timeout_12"])

    def test_small_timeout_untouched(self):
        self.write_repo_config({"difficulty": {"backend": "fake", "timeout_s": 5}})
        self.submit()
        ev = [e for e in self.log_events() if e["event"] == "route"][0]
        self.assertNotIn("timeout_clamped", ev)
        self.assertEqual(ev["decision"]["reason_codes"], ["timeout_5"])


class MiscTest(HookCase):
    def test_error_log_has_no_exception_text(self):
        (self.repo / ".model-effort-router.json").write_text('{"SECRET_TOKEN_XYZ": ')
        self.submit()
        (err,) = [e for e in self.log_events() if e["event"] == "error"]
        self.assertEqual(set(err) - {"ts"}, {"event", "type", "code"})
        self.assertNotIn("SECRET_TOKEN_XYZ", json.dumps(err))

    def test_production_code_has_no_fake_backend(self):
        for p in (ROOT / "model_effort_router").rglob("*.py"):
            self.assertNotIn("_FakeBackend", p.read_text())

    def test_registry_module_must_be_under_tests(self):
        self.assertEqual(self.submit(env_extra={"MER_TEST_REGISTRY_MODULE": "os"}).stdout, "")

    def test_session_log_filename_safe_and_collision_free(self):
        import os
        from model_effort_router.logging import route_log
        d = str(self.state)
        self.assertEqual(os.path.dirname(route_log.log_path(d, "../../x")), d)
        self.assertNotEqual(route_log.log_path(d, "a/b"), route_log.log_path(d, "a_b"))

    def test_orchestration_is_gone(self):
        for rel in ("model_effort_router/host/state.py", "model_effort_router/host/instructions.py",
                    "model_effort_router/policy/stages.py", "plugins/codex-model-effort-router/hooks/pre_tool_use.py"):
            self.assertFalse((ROOT / rel).exists(), rel)


if __name__ == "__main__":
    unittest.main()

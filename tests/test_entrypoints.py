import os
import unittest
from pathlib import Path
from unittest.mock import patch

from model_effort_router import entrypoints


class EntrypointsTest(unittest.TestCase):
    def test_model_effort_router_forwards_to_function_entrypoints(self):
        class ExampleRouter(entrypoints.ModelEffortRouter):
            host = "claude"
            gate_host = "claude"
            runtime_api = 1

        with patch.object(entrypoints, "cli", return_value=7) as call:
            self.assertEqual(ExampleRouter.run_cli(), 7)
            call.assert_called_once_with("claude", runtime_api=1)
        with patch.object(entrypoints, "gate", return_value=3) as call:
            self.assertEqual(ExampleRouter.run_gate(), 3)
            call.assert_called_once_with("claude", runtime_api=1)
        root = Path("/tmp/plugin")
        with patch.object(entrypoints, "hook", return_value=5) as call:
            self.assertEqual(ExampleRouter.run_hook(root), 5)
            call.assert_called_once_with("claude", root, runtime_api=1)

    def test_model_effort_router_preserves_antigravity_gate_environment(self):
        class AntigravityRouter(entrypoints.ModelEffortRouter):
            host = "antigravity"
            gate_host = None
            runtime_api = 1

        with patch.object(entrypoints, "gate", return_value=4) as call:
            self.assertEqual(AntigravityRouter.run_gate(), 4)
            call.assert_called_once_with(None, runtime_api=1)

    def test_runtime_api_mismatch_does_not_start_cli_or_change_host(self):
        with patch.dict(os.environ, {"MER_HOST": "claude"}):
            with self.assertRaises(entrypoints.RuntimeCompatibilityError):
                entrypoints.cli("codex", runtime_api=999)
            self.assertEqual(os.environ["MER_HOST"], "claude")
            with self.assertRaises(entrypoints.RuntimeCompatibilityError):
                entrypoints.gate("codex", runtime_api=999)
            self.assertEqual(entrypoints.hook("codex", Path("/tmp/plugin"), runtime_api=999), 0)
            self.assertEqual(os.environ["MER_HOST"], "claude")

    def test_cli_pins_host_at_call_time_and_returns_exit_code(self):
        with patch.dict(os.environ, {"MER_HOST": "codex"}):
            with patch(
                "model_effort_router.cli.main", side_effect=lambda: 7 if os.environ["MER_HOST"] == "claude" else 9
            ):
                self.assertEqual(entrypoints.cli("claude"), 7)

    def test_cli_propagates_errors(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("model_effort_router.cli.main", side_effect=RuntimeError("boom")):
                with self.assertRaisesRegex(RuntimeError, "boom"):
                    entrypoints.cli("codex")

    def test_gate_pins_explicit_host_and_returns_exit_code(self):
        with patch.dict(os.environ, {"MER_HOST": "claude"}):
            with patch(
                "model_effort_router.gate.run.main", side_effect=lambda: 3 if os.environ["MER_HOST"] == "codex" else 9
            ) as main:
                self.assertEqual(entrypoints.gate("codex"), 3)
                main.assert_called_once_with()

    def test_gate_without_host_preserves_existing_environment(self):
        with patch.dict(os.environ, {"MER_HOST": "claude"}):
            with patch("model_effort_router.gate.run.main", return_value=4) as main:
                self.assertEqual(entrypoints.gate(), 4)
                self.assertEqual(os.environ["MER_HOST"], "claude")
                main.assert_called_once_with()

    def test_gate_without_host_leaves_absent_environment_absent(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("model_effort_router.gate.run.main", return_value=0):
                self.assertEqual(entrypoints.gate(), 0)
                self.assertNotIn("MER_HOST", os.environ)

    def test_gate_propagates_errors(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("model_effort_router.gate.run.main", side_effect=ValueError("boom")):
                with self.assertRaisesRegex(ValueError, "boom"):
                    entrypoints.gate("claude")

    def test_missing_cli_or_gate_module_returns_install_hint(self):
        import io
        from contextlib import redirect_stderr

        errors = io.StringIO()
        with patch(
            "model_effort_router.entrypoints.importlib.import_module", side_effect=ModuleNotFoundError("missing")
        ):
            with redirect_stderr(errors):
                self.assertEqual(entrypoints.cli("codex"), 2)
                self.assertEqual(entrypoints.gate("codex"), 2)
        self.assertIn("install_core.py", errors.getvalue())

    def test_hook_forwards_host_event_and_plugin_root(self):
        root = Path("/tmp/plugin")
        with patch.dict(os.environ, {}, clear=True):
            with patch("model_effort_router.host.codex_hooks.main", return_value=5) as main:
                self.assertEqual(entrypoints.hook("codex", root), 5)
                self.assertEqual(os.environ["MER_HOST"], "codex")
                main.assert_called_once_with("UserPromptSubmit", root)

    def test_hook_forwards_a_non_default_event(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("model_effort_router.host.codex_hooks.main", return_value=0) as main:
                entrypoints.hook("claude", Path("/p"), event="SessionStart")
                main.assert_called_once_with("SessionStart", Path("/p"))

    def test_hook_swallows_ordinary_and_system_exit_errors(self):
        for error in (RuntimeError("boom"), SystemExit(2)):
            with self.subTest(error=type(error).__name__), patch.dict(os.environ, {}, clear=True):
                with patch("model_effort_router.host.codex_hooks.main", side_effect=error):
                    self.assertEqual(entrypoints.hook("claude", Path("/tmp/plugin")), 0)


if __name__ == "__main__":
    unittest.main()

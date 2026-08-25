from pathlib import Path
from unittest import mock
import importlib.util
import json
import os
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("prompt_hook", ROOT / "scripts" / "prompt_hook.py")
prompt_hook = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = prompt_hook
SPEC.loader.exec_module(prompt_hook)


ROUTE = {
    "schema_version": 1,
    "platform": "codex",
    "mode": "single",
    "steps": [{"command": ["codex", "exec", "-m", "gpt-5.6-sol", "--", "do the work"]}],
}


class PromptHookTests(unittest.TestCase):
    def test_accepts_codex_and_claude_prompt_fields(self):
        self.assertEqual(prompt_hook.extract_prompt({"prompt": "fix it"}), "fix it")
        self.assertEqual(prompt_hook.extract_prompt({"user_prompt": "fix it"}), "fix it")
        self.assertIsNone(prompt_hook.extract_prompt({"prompt": "   "}))

    def test_bypass_never_starts_a_nested_route(self):
        with mock.patch.object(prompt_hook, "run_route") as run_route:
            response = prompt_hook.handle_payload({"prompt": "fix it"}, "codex", ROOT, {"MODEL_EFFORT_ROUTER_HOOK_BYPASS": "1"})
        self.assertIsNone(response)
        run_route.assert_not_called()

    def test_forces_one_classification_then_replays_the_saved_route(self):
        completed = [
            subprocess.CompletedProcess([], 0, json.dumps(ROUTE), ""),
            subprocess.CompletedProcess([], 0, "codex exec -m gpt-5.6-sol -- 'do the work'\n", ""),
            subprocess.CompletedProcess([], 0, "", ""),
        ]
        with mock.patch.object(prompt_hook.subprocess, "run", side_effect=completed) as run:
            response = prompt_hook.handle_payload({"prompt": "fix it", "cwd": str(ROOT)}, "codex", ROOT, {})

        self.assertEqual(response["decision"], "block")
        self.assertIn("completed", response["reason"])
        classify, replay, execute = run.call_args_list
        self.assertIn("--format", classify.args[0])
        self.assertIn("json", classify.args[0])
        self.assertEqual(replay.args[0][2], "--route-file")
        self.assertEqual(execute.args[0][:2], ["bash", "-c"])
        self.assertIs(execute.kwargs["stdout"], sys.stderr)
        self.assertIs(execute.kwargs["stderr"], sys.stderr)
        for call in run.call_args_list:
            self.assertEqual(call.kwargs["env"]["MODEL_EFFORT_ROUTER_HOOK_BYPASS"], "1")

    def test_route_failure_still_blocks_the_default_session(self):
        failed = subprocess.CompletedProcess([], 1, "", "classifier unavailable")
        with mock.patch.object(prompt_hook.subprocess, "run", return_value=failed):
            response = prompt_hook.handle_payload({"prompt": "fix it"}, "codex", ROOT, os.environ.copy())
        self.assertEqual(response["decision"], "block")
        self.assertIn("failed", response["reason"])


if __name__ == "__main__":
    unittest.main()

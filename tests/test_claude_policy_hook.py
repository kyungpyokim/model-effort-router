from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "claude-model-effort-router"
HOOKS = PLUGIN / "hooks" / "hooks.json"
HOOK = PLUGIN / "scripts" / "routing_policy_hook.py"


def run_hook(stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK), "SessionStart"],
        input=stdin,
        text=True,
        capture_output=True,
        timeout=3,
    )


class ClaudePolicyHookTests(unittest.TestCase):
    def test_hook_configuration_injects_policy_at_session_start_only(self):
        payload = json.loads(HOOKS.read_text(encoding="utf-8"))
        self.assertEqual(set(payload["hooks"]), {"SessionStart"})
        session_start = payload["hooks"]["SessionStart"][0]
        self.assertEqual(session_start["matcher"], "^(startup|resume|clear|compact)$")
        handler = session_start["hooks"][0]
        self.assertEqual(handler["type"], "command")
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/scripts/routing_policy_hook.py", handler["command"])
        self.assertEqual(handler["timeout"], 2)
        self.assertFalse(handler.get("async", False))
        for forbidden in ("router.py", "claude-route", "claude -p"):
            self.assertNotIn(forbidden, handler["command"])

    def test_hook_returns_non_blocking_session_start_context(self):
        result = run_hook(json.dumps({"source": "startup"}))
        self.assertEqual(result.returncode, 0)
        response = json.loads(result.stdout)
        self.assertNotIn("decision", response)
        self.assertNotEqual(response.get("continue"), False)
        context = response["hookSpecificOutput"]
        self.assertEqual(context["hookEventName"], "SessionStart")
        self.assertLessEqual(len(context["additionalContext"]), 1000)
        for expected in (
            "model-effort:route skill",
            "Agent tool",
            "same-scope follow-ups",
            "casual chat or status-only questions",
            "executor given a complete route",
            "do not delegate it",
        ):
            self.assertIn(expected, context["additionalContext"])

    def test_policy_routes_code_changes_through_the_pipeline_launcher(self):
        result = run_hook(json.dumps({"source": "startup"}))
        policy = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        for expected in (
            "pipeline block is non-null (code changes)",
            "scripts/pipeline.py --route-file",
            "plan, implement, test, review and fix",
            "never the parent implementing directly",
            "Only pipeline-null routes (design/review) are delegated with the Agent tool",
            "Show task_type, level, model/effort, source before delegating",
        ):
            self.assertIn(expected, policy)
        for stale in ("single-agent fast path", "bounded changes", "L1-L3", "merged Opus", "implement directly"):
            self.assertNotIn(stale, policy)

    def test_malformed_input_is_ignored_without_failing_the_host(self):
        result = run_hook("not json")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "{}\n")

    def test_manifest_relies_on_hook_auto_discovery(self):
        manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertNotIn("hooks", manifest)


if __name__ == "__main__":
    unittest.main()

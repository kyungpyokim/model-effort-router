from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "codex-model-effort-router"
HOOKS = PLUGIN / "hooks" / "hooks.json"
HOOK = PLUGIN / "scripts" / "routing_policy_hook.py"


class CodexPolicyHookTests(unittest.TestCase):
    def test_hook_configuration_only_injects_short_policy_context(self):
        payload = json.loads(HOOKS.read_text(encoding="utf-8"))
        self.assertEqual(set(payload["hooks"]), {"SessionStart"})
        session_start = payload["hooks"]["SessionStart"][0]
        self.assertEqual(session_start["matcher"], "^(startup|resume|clear|compact)$")
        handler = session_start["hooks"][0]
        self.assertEqual(handler["type"], "command")
        self.assertIn("${PLUGIN_ROOT}/scripts/routing_policy_hook.py", handler["command"])
        self.assertEqual(handler["timeout"], 2)
        self.assertEqual(handler["additionalContextLimit"], 1000)
        self.assertFalse(handler.get("async", False))
        for forbidden in ("router.py", "codex-route", "codex exec", "claude", "agy"):
            self.assertNotIn(forbidden, handler["command"])

    def test_hook_returns_context_without_blocking_or_starting_a_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            counter = temp / "executed"
            for executable in ("codex", "claude", "agy"):
                target = temp / executable
                target.write_text(f"#!/bin/sh\ntouch {counter}\n", encoding="utf-8")
                target.chmod(0o755)
            result = subprocess.run(
                [sys.executable, str(HOOK), "SessionStart"],
                input=json.dumps({"source": "startup"}),
                text=True,
                capture_output=True,
                timeout=3,
                check=True,
                env={"PATH": f"{temp}:{Path('/usr/bin')}"},
            )
            response = json.loads(result.stdout)
            self.assertNotIn("decision", response)
            self.assertNotEqual(response.get("continue"), False)
            context = response["hookSpecificOutput"]
            self.assertEqual(context["hookEventName"], "SessionStart")
            self.assertLessEqual(len(context["additionalContext"]), 1000)
            self.assertFalse(counter.exists())

    def test_policy_distinguishes_new_work_follow_ups_reviews_and_executors(self):
        result = subprocess.run(
            [sys.executable, str(HOOK), "SessionStart"],
            input="{}",
            text=True,
            capture_output=True,
            timeout=3,
            check=True,
        )
        policy = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        for expected in (
            "implementation, design, review, refactoring, or debugging",
            "same-scope follow-ups",
            "a distinct task, a new review, materially increased scope/risk",
            "casual chat or status-only questions",
            "classification-only process",
            "executor given a complete route",
            "not successful semantic routing",
        ):
            self.assertIn(expected, policy)

    def test_malformed_input_is_ignored_without_failing_the_host(self):
        result = subprocess.run(
            [sys.executable, str(HOOK), "SessionStart"],
            input="not json",
            text=True,
            capture_output=True,
            timeout=3,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "{}\n")

    def test_codex_skill_documents_route_first_and_no_reroute_contract(self):
        skill = " ".join((PLUGIN / "skills" / "route" / "SKILL.md").read_text(encoding="utf-8").split())
        for expected in (
            "substantive coding task",
            "same-scope follow-up",
            "new review",
            "materially raises scope or risk",
            "Do not route casual chat or status-only questions",
            "does not invoke this router again",
        ):
            self.assertIn(expected, skill)

    def test_codex_manifest_and_validator_include_only_the_codex_hook_release(self):
        manifest = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "2.1.2")
        self.assertNotIn("hooks", manifest)
        validator = (ROOT / "scripts" / "validate_bundle.py").read_text(encoding="utf-8")
        self.assertIn('codex / "hooks" / "hooks.json"', validator)
        self.assertNotIn('claude / "hooks"', validator)
        self.assertNotIn('agy / "hooks"', validator)


if __name__ == "__main__":
    unittest.main()

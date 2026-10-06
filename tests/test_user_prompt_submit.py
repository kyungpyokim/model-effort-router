import json
import unittest

from tests.hook_helpers import DEV, HookCase, run_script


class UserPromptSubmitTest(HookCase):
    def context(self, proc):
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        hook = payload["hookSpecificOutput"]
        self.assertEqual(hook["hookEventName"], "UserPromptSubmit")
        return hook["additionalContext"]

    def test_advisory_includes_role_effort_model_and_context_packet(self):
        self.fake = {"role": "review", "effort": "medium", "confidence": 0.8}
        advice = self.context(self.submit("Review the diff in parser.py"))
        self.assertIn("Role: review", advice)
        self.assertIn("worker lane: reasoning", advice)
        self.assertIn("gpt-6.1-sol", advice)
        self.assertIn("goal, decisions, constraints, actual diff, verification status/results", advice)
        self.assertIn("current request and relevant conversation", advice)
        self.assertIn("populate", advice)
        self.assertIn("native Subagent invocation", advice)
        self.assertIn("actual diff", advice)
        self.assertIn("verification status/results", advice)
        self.assertIn("not run", advice)
        self.assertIn("full conversation", advice)
        self.assertIn("private reasoning", advice)
        self.assertIn("does not change this Main turn", advice)
        self.assertNotIn("L1", advice)

    def test_risk_floor_only_raises_effort_for_protected_roles(self):
        self.fake = {"role": "review", "effort": "low"}
        advice = self.context(self.submit("Review the migration that drops the old records in db.py"))
        self.assertIn("effort: high", advice)
        self.assertIn("Role: review", advice)

    def test_explicit_phase_override_skips_classifier(self):
        self.fake = {"raise": True}
        advice = self.context(self.submit("/router role=analysis effort=xhigh\nAnalyze parser.py"))
        self.assertIn("Role: analysis", advice)
        self.assertIn("effort: xhigh", advice)

    def test_classifier_failure_is_fail_open_and_recorded_without_prompt(self):
        self.fake = {"raise": True}
        proc = self.submit()
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))
        events = self.log_events()
        self.assertEqual([ev["event"] for ev in events], ["error"])
        self.assertNotIn("ZEBRA_PROMPT_MARKER", json.dumps(events))

    def test_bad_config_and_garbage_input_fail_open(self):
        (self.repo / ".model-effort-router.json").write_text("{not json")
        self.assertEqual((self.submit().returncode, self.submit().stdout), (0, ""))
        proc = run_script("hooks/user_prompt_submit.py", stdin="not json", env=self.env())
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))

    def test_non_development_and_host_generated_prompts_are_not_classified(self):
        for prompt in (
            "What is the capital of France?",
            "Another Claude session sent a message:\n<agent-message>Fix the bug in parser.py</agent-message>",
            "<task-notification>refactor parser.py</task-notification>",
        ):
            proc = self.submit(prompt)
            self.assertEqual((proc.returncode, proc.stdout), (0, ""), prompt)
        self.assertEqual(self.log_events(), [])

    def test_readonly_code_analysis_is_route_eligible(self):
        self.fake = {"role": "analysis", "effort": "high"}
        advice = self.context(self.submit("Analyze the authentication flow in auth.py"))
        self.assertIn("Role: analysis", advice)

    def test_off_and_manual_modes_remain_silent_without_phase_override(self):
        self.write_repo_config({"router": {"mode": "off"}, "difficulty": {"backend": "fake"}})
        self.assertEqual(self.submit().stdout, "")
        self.write_repo_config({"router": {"mode": "manual"}, "difficulty": {"backend": "fake"}})
        self.assertEqual(self.submit().stdout, "")

    def test_route_log_contains_hash_and_role_effort_without_prompt(self):
        self.fake = {"role": "fix", "effort": "medium"}
        self.context(self.submit())
        (event,) = self.log_events()
        self.assertEqual((event["event"], event["decision"]["role"], event["decision"]["effort"]),
                         ("route", "fix", "medium"))
        self.assertEqual((event["prompt_len"], len(event["prompt_sha"])), (len(DEV), 12))
        self.assertNotIn("ZEBRA_PROMPT_MARKER", json.dumps(event))
        self.assertNotIn("prompt", event)

    def test_log_failure_does_not_change_advisory_output(self):
        blocker = self.root / "file"
        blocker.write_text("x")
        proc = run_script("hooks/user_prompt_submit.py", env=self.env(MER_STATE_DIR=str(blocker / "sub")),
                          stdin=json.dumps({"session_id": "s", "cwd": str(self.repo), "prompt": DEV}))
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Role:", self.context(proc))


if __name__ == "__main__":
    unittest.main()

import unittest

from tests.hook_helpers import SID, HookCase, decision, run_script

PLAN = dict(model="gpt-6-sol", reasoning_effort="high")
IMPL = dict(model="gpt-6-luna", reasoning_effort="high")
REVIEW = dict(model="gpt-6-sol", reasoning_effort="high")


class PreToolUseTest(HookCase):
    def setUp(self):
        super().setUp()
        self.submit()  # L3 plan with plan/implement/review

    def assertAllowed(self, proc):
        self.assertIsNone(decision(proc))

    def assertDenied(self, proc, *needles):
        d = decision(proc)
        self.assertEqual(d["permissionDecision"], "deny")
        for n in needles:
            self.assertIn(n, d["permissionDecisionReason"])
        return d

    def status(self, stage):
        return self.plan_state()["stages"][stage]["status"]

    def test_non_mer_spawn_allowed(self):
        self.assertAllowed(self.spawn(None, model="anything"))

    def test_non_spawn_tool_ignored(self):
        self.assertAllowed(self.spawn("plan", tool="Bash", model="wrong"))

    def test_session_without_plan_allowed(self):
        self.assertAllowed(self.spawn("plan", sid="other", model="wrong"))

    def test_stage_not_in_plan_allowed(self):
        self.assertAllowed(self.spawn("docs", model="wrong"))

    def test_matching_spawn_allowed_and_marks_running(self):
        self.assertAllowed(self.spawn("plan", **PLAN))
        self.assertEqual(self.status("plan"), "running")

    def test_plain_spawn_agent_tool_name_also_guarded(self):
        self.assertDenied(self.spawn("plan", tool="spawn_agent", **IMPL))

    def test_wrong_model_denied_with_required_values(self):
        self.assertDenied(self.spawn("plan", model="gpt-6-luna", reasoning_effort="high"),
                          'model="gpt-6-sol"', 'reasoning_effort="high"', 'fork_turns="none"')
        self.assertEqual(self.status("plan"), "pending")

    def test_wrong_effort_denied(self):
        self.assertDenied(self.spawn("plan", model="gpt-6-sol", reasoning_effort="low"), "effort")

    def test_missing_model_and_effort_denied(self):
        self.assertDenied(self.spawn("plan"), "model")

    def test_fork_turns_all_or_missing_denied(self):
        self.assertDenied(self.spawn("plan", fork_turns="all", **PLAN), "fork_turns")
        self.assertDenied(self.spawn("plan", fork_turns=None, **PLAN), "fork_turns")

    def test_duplicate_running_stage_denied(self):
        self.assertAllowed(self.spawn("plan", **PLAN))
        self.assertDenied(self.spawn("plan", **PLAN), "already running", "--mark plan failed")

    def test_next_stage_marks_previous_done_and_done_stage_not_respawned(self):
        self.spawn("plan", **PLAN)
        self.assertAllowed(self.spawn("implement", **IMPL))
        self.assertEqual(self.status("plan"), "done")
        self.assertDenied(self.spawn("plan", **PLAN), "already done")

    def test_failed_or_cancelled_stage_can_be_respawned(self):
        self.spawn("plan", **PLAN)
        p = run_script("bin/mer-gate", argv=["--session", SID, "--mark", "plan", "failed"],
                       env=self.env(), cwd=str(self.repo))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.status("plan"), "failed")
        self.assertAllowed(self.spawn("plan", **PLAN))

    def test_fix_loop_allows_two_implement_respawns_and_review_reruns(self):
        self.spawn("plan", **PLAN)
        self.spawn("implement", **IMPL)
        self.assertAllowed(self.spawn("review", **REVIEW))
        self.assertDenied(self.spawn("review", **REVIEW), "running")
        for n in (1, 2):
            self.assertAllowed(self.spawn("implement", **IMPL))  # fix round n
            self.assertEqual(self.plan_state()["fix_count"], n)
            self.assertEqual(self.status("review"), "pending")
            self.assertAllowed(self.spawn("review", **REVIEW))
        self.assertDenied(self.spawn("implement", **IMPL), "Fix limit", "2")
        self.assertEqual(self.plan_state()["fix_count"], 2)

    def test_implement_respawn_while_running_denied(self):
        self.spawn("implement", **IMPL)
        self.assertDenied(self.spawn("implement", **IMPL), "already running")
        self.assertEqual(self.plan_state()["fix_count"], 0)

    def test_spawn_events_logged(self):
        self.spawn("plan", **PLAN)
        self.spawn("plan", **PLAN)
        evs = [e for e in self.log_events() if e["event"] == "stage_spawn"]
        self.assertEqual([(e["stage"], e["decision"]) for e in evs],
                         [("plan", "allow"), ("plan", "deny")])
        self.assertEqual(evs[0]["model"], "gpt-6-sol")
        self.assertEqual(evs[0]["effort"], "high")

    def test_spawn_event_records_fix_count(self):
        self.spawn("implement", **IMPL)
        self.spawn("review", **REVIEW)
        self.spawn("implement", **IMPL)  # fix round 1
        evs = [e for e in self.log_events() if e["event"] == "stage_spawn"]
        self.assertEqual([e["fix_count"] for e in evs], [0, 0, 1])

    def test_corrupt_state_fails_open(self):
        self.plan_file().write_text("{oops")
        self.assertAllowed(self.spawn("plan", model="wrong"))
        self.assertTrue([e for e in self.log_events() if e["event"] == "error"])

    def test_garbage_stdin_fails_open(self):
        p = run_script("hooks/pre_tool_use.py", stdin="[1,2", env=self.env())
        self.assertEqual((p.returncode, p.stdout), (0, ""))

    def test_guard_env_is_noop(self):
        p = run_script("hooks/pre_tool_use.py", stdin="{}", env=self.env(MER_CLASSIFIER="1"))
        self.assertEqual((p.returncode, p.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()

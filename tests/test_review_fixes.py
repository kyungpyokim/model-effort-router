import json
import os
import stat
import time
import unittest

from model_effort_router.host import state as hs
from tests.hook_helpers import DEV, SID, HookCase, decision, run_script

IMPL = dict(model="gpt-6-luna", reasoning_effort="high")
PLAN = dict(model="gpt-6-sol", reasoning_effort="high")


def mark(case, stage, status):
    p = run_script("bin/mer-gate", env=case.env(), cwd=str(case.repo),
                   argv=["--session", SID, "--mark", stage, status])
    assert p.returncode == 0, p.stderr


class FixBudgetTest(HookCase):
    def setUp(self):
        super().setUp()
        self.submit()

    def test_mark_failed_cannot_bypass_fix_budget(self):
        self.assertIsNone(decision(self.spawn("implement", **IMPL)))
        for n in (1, 2):
            mark(self, "implement", "failed")
            self.assertIsNone(decision(self.spawn("implement", **IMPL)))
            self.assertEqual(self.plan_state()["fix_count"], n)
        mark(self, "implement", "cancelled")
        d = decision(self.spawn("implement", **IMPL))
        self.assertEqual(d["permissionDecision"], "deny")
        self.assertIn("Fix limit", d["permissionDecisionReason"])


class StaleRunningTest(unittest.TestCase):
    def state(self):
        stub = type("P", (), {})()
        from model_effort_router.policy.router import route
        from tests.fake_registry import register
        reg = {}
        register(reg, {"MER_TEST_FAKE_BACKEND": '{"level":"L3"}'})
        plan = route("Fix the bug in parser.py", repo_config={"difficulty": {"backend": "fake"}}, registry=reg)
        return hs.build_state(plan, session_id="s", gate_cmd="/g", now=1000.0)

    def ti(self, stage, st):
        s = st["stages"][stage]
        return {"task_name": f"mer-{stage}", "fork_turns": "none", "model": s["model"],
                "reasoning_effort": s["effort"]}

    def test_running_not_stale_denied_then_stale_allowed(self):
        st = self.state()
        _, _, _, st = hs.check_spawn(st, self.ti("plan", st), now=1000.0)
        d, reason, _, _ = hs.check_spawn(st, self.ti("plan", st), now=1000.0 + hs.STALE_RUNNING_S - 1)
        self.assertEqual(d, "deny")
        d, _, _, st2 = hs.check_spawn(st, self.ti("plan", st), now=1000.0 + hs.STALE_RUNNING_S + 1)
        self.assertEqual(d, "allow")
        self.assertEqual(st2["stages"]["plan"]["spawns"], 2)

    def test_stale_implement_respawn_counts_toward_fix_budget(self):
        st = self.state()
        _, _, _, st = hs.check_spawn(st, self.ti("implement", st), now=1000.0)
        d, _, _, st = hs.check_spawn(st, self.ti("implement", st), now=1000.0 + hs.STALE_RUNNING_S + 1)
        self.assertEqual((d, st["fix_count"]), ("allow", 1))

    def test_age_out_rules(self):
        st = self.state()
        self.assertEqual(hs.after_no_route(st, 1001.0)[0], "keep")
        self.assertEqual(hs.after_no_route(st, 1000.0 + hs.PLAN_TTL_S + 1)[0], "drop")
        for s in st["stages"].values():
            s["status"] = "done"
        self.assertEqual(hs.after_no_route(st, 1001.0)[0], "drop")
        st = self.state()
        _, st = hs.after_no_route(st, 1001.0)
        _, st = hs.after_no_route(st, 1002.0)
        self.assertEqual(hs.after_no_route(st, 1003.0)[0], "drop")


class PlanAgeOutTest(HookCase):
    Q = "What is the capital of France?"

    def test_one_no_route_keeps_plan(self):
        self.submit()
        self.submit(self.Q)
        self.assertTrue(self.plan_file().exists())

    def test_three_consecutive_no_route_drop_plan(self):
        self.submit()
        for _ in range(3):
            self.submit(self.Q)
        self.assertFalse(self.plan_file().exists())

    def test_routed_prompt_resets_counter(self):
        self.submit()
        self.submit(self.Q)
        self.submit(self.Q)
        self.submit()
        self.submit(self.Q)
        self.assertTrue(self.plan_file().exists())

    def test_old_plan_dropped(self):
        self.submit()
        st = self.plan_state()
        st["created"] -= 3 * 3600
        self.plan_file().write_text(json.dumps(st))
        self.submit(self.Q)
        self.assertFalse(self.plan_file().exists())

    def test_all_done_dropped(self):
        self.submit()
        for stage in ("plan", "implement", "review"):
            mark(self, stage, "done")
        self.submit(self.Q)
        self.assertFalse(self.plan_file().exists())


class UnwritableStateTest(HookCase):
    def test_deny_survives_unwritable_state(self):
        self.submit()
        os.chmod(self.state, stat.S_IRUSR | stat.S_IXUSR)
        self.addCleanup(os.chmod, self.state, stat.S_IRWXU)
        d = decision(self.spawn("plan", model="wrong", reasoning_effort="high"))
        self.assertEqual(d["permissionDecision"], "deny")

    def test_allow_survives_unwritable_state(self):
        self.submit()
        os.chmod(self.state, stat.S_IRUSR | stat.S_IXUSR)
        self.addCleanup(os.chmod, self.state, stat.S_IRWXU)
        self.assertIsNone(decision(self.spawn("plan", **PLAN)))

    def test_injection_survives_unwritable_state(self):
        blocker = self.root / "file"
        blocker.write_text("x")
        p = run_script("hooks/user_prompt_submit.py", env=self.env(MER_STATE_DIR=str(blocker / "sub")),
                       stdin=json.dumps({"session_id": SID, "cwd": str(self.repo), "prompt": DEV}))
        self.assertIn("mer-implement", json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"])


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
        from tests.hook_helpers import ROOT
        for p in (ROOT / "model_effort_router").rglob("*.py"):
            self.assertNotIn("_FakeBackend", p.read_text())

    def test_registry_module_must_be_under_tests(self):
        p = self.submit(env_extra={"MER_TEST_REGISTRY_MODULE": "os"})
        self.assertEqual(p.stdout, "")

    def test_session_filename_safe_and_collision_free(self):
        d = str(self.state)
        evil = hs.plan_path(d, "../../x")
        self.assertEqual(os.path.dirname(evil), d)
        self.assertNotEqual(hs.plan_path(d, "a/b"), hs.plan_path(d, "a_b"))
        self.assertNotEqual(hs.log_path(d, "a/b"), hs.log_path(d, "a_b"))

    def test_state_has_no_dead_fields(self):
        self.submit()
        st = self.plan_state()
        self.assertNotIn("turn_id", st)
        self.assertNotIn("gate", st)
        self.assertIn("created", st)

    def test_instructions_mention_gate_runs_repo_commands_via_shell(self):
        ctx = json.loads(self.submit().stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("repo-defined commands", ctx)
        self.assertIn("never run by hooks", ctx)
        self.assertIn("--mark review done", ctx)


if __name__ == "__main__":
    unittest.main()

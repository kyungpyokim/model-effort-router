import unittest

from model_effort_router.difficulty.decision import DifficultyDecision
from model_effort_router.policy.router import route
from model_effort_router.profiles.profiles import Profile
from model_effort_router.policy.session import session_plan

DEV = "Fix the bug in parser.py"


class FakeBackend:
    def __init__(self, name="fake", level="L3", flags=(), exc=None, confidence=None):
        self.name, self.level, self.flags, self.exc = name, level, flags, exc
        self.confidence = confidence
        self.calls = []

    def classify(self, task, timeout_s):
        self.calls.append((task, timeout_s))
        if self.exc:
            raise self.exc
        return DifficultyDecision(
            self.level, self.name, risk_flags=self.flags, confidence=self.confidence
        )


def reg(*backends):
    return {b.name: (lambda b=b: b) for b in backends}


def sp(plan):
    return session_plan(plan.decision, plan.risk_flags, plan.overrides)


class RouteTest(unittest.TestCase):
    def test_full_route(self):
        b = FakeBackend(level="L3")
        plan = route(DEV, registry=reg(b), repo_config={"difficulty": {"backend": "fake"}})
        self.assertEqual(plan.target, "route")
        self.assertEqual(plan.decision.level, "L3")
        self.assertEqual(sp(plan).start, Profile("balanced", "high"))
        self.assertEqual(b.calls[0][1], 10)  # default timeout_s

    def test_chat_is_not_routed_and_backend_not_called(self):
        b = FakeBackend()
        plan = route("hello there", registry=reg(b), repo_config={"difficulty": {"backend": "fake"}})
        self.assertEqual(plan.target, "no_route")
        self.assertIsNone(plan.decision)
        self.assertEqual(b.calls, [])

    def test_plan_only_and_review_only(self):
        b = FakeBackend(level="L2")
        cfg = {"difficulty": {"backend": "fake"}}
        p = route("Write an implementation plan for the new API endpoint", registry=reg(b), repo_config=cfg)
        self.assertEqual(p.target, "plan_only")
        r = route("Review my code", registry=reg(b), repo_config=cfg)
        self.assertEqual((r.target, r.decision.level), ("review_only", "L2"))

    def test_risk_flags_merged_with_backend_flags(self):
        b = FakeBackend(level="L2", flags=("auth",))
        plan = route(
            "Fix the payment retry bug in billing.py",
            registry=reg(b),
            repo_config={"difficulty": {"backend": "fake"}},
        )
        self.assertEqual(plan.decision.risk_flags, ("auth", "payment"))
        self.assertIn("risk_min:payment", sp(plan).applied_rules)
        self.assertTrue(sp(plan).plan_first)

    def test_backend_receives_task_without_override_line_and_paths(self):
        b = FakeBackend()
        route("/router auto\n" + DEV, paths=["src/parser.py"], registry=reg(b),
              repo_config={"difficulty": {"backend": "fake"}})
        task = b.calls[0][0]
        self.assertEqual(task.task, DEV)
        self.assertEqual(tuple(task.paths), ("src/parser.py",))

    def test_fallback_chain_primary_then_fallback(self):
        p = FakeBackend("p", exc=TimeoutError())
        f = FakeBackend("f", level="L4")
        plan = route(DEV, registry=reg(p, f),
                     repo_config={"difficulty": {"backend": "p", "fallback": "f"}})
        self.assertEqual((plan.decision.backend, plan.decision.level), ("f", "L4"))

    def test_all_fail_default_l3_with_risk_minimum_applied(self):
        p = FakeBackend("p", exc=RuntimeError())
        plan = route("Fix the code that may cause data loss when it drops table rows",
                     registry=reg(p), repo_config={"difficulty": {"backend": "p"}})
        self.assertEqual((plan.decision.backend, plan.decision.level), ("default", "L3"))
        self.assertIn("data_loss", plan.decision.risk_flags)
        self.assertTrue(sp(plan).plan_first)  # data_loss: plan-first (and, with subagents off, a review: test_session_plan)

    def test_unknown_backend_name_is_a_config_error(self):
        with self.assertRaises(ValueError):
            route(DEV, registry={}, repo_config={"difficulty": {"backend": "nope"}})

    def test_factory_failure_degrades_to_default_with_cause(self):
        def boom():
            raise RuntimeError("x")

        plan = route(DEV, registry={"p": boom}, repo_config={"difficulty": {"backend": "p"}})
        self.assertEqual((plan.decision.backend, plan.decision.level), ("default", "L3"))
        self.assertEqual(plan.decision.reason_codes, ("p:RuntimeError",))

    def test_timeout_from_config(self):
        b = FakeBackend()
        route(DEV, registry=reg(b), repo_config={"difficulty": {"backend": "fake", "timeout_s": 4}})
        self.assertEqual(b.calls[0][1], 4)


class ModeAndOverrideTest(unittest.TestCase):
    CFG = {"difficulty": {"backend": "fake"}}

    def test_typed_off_disables(self):
        b = FakeBackend()
        plan = route("/router off\n" + DEV, registry=reg(b), repo_config=self.CFG)
        self.assertEqual((plan.target, plan.mode), ("no_route", "off"))
        self.assertEqual(b.calls, [])

    def test_repo_off_disables_but_typed_auto_wins(self):
        b = FakeBackend()
        repo = {"router": {"mode": "off"}, **self.CFG}
        self.assertEqual(route(DEV, registry=reg(b), repo_config=repo).target, "no_route")
        plan = route("/router auto\n" + DEV, registry=reg(b), repo_config=repo)
        self.assertEqual((plan.target, plan.mode), ("route", "auto"))

    def test_user_config_lowest_precedence(self):
        b = FakeBackend()
        user = {"router": {"mode": "off"}, **self.CFG}
        self.assertEqual(route(DEV, registry=reg(b), user_config=user).mode, "off")
        repo = {"router": {"mode": "auto"}}
        self.assertEqual(route(DEV, registry=reg(b), user_config=user, repo_config=repo).mode, "auto")

    def test_quoted_off_is_ignored(self):
        b = FakeBackend()
        plan = route("> /router off\n" + DEV, registry=reg(b), repo_config=self.CFG)
        self.assertEqual((plan.mode, plan.target), ("auto", "route"))
        plan = route(DEV + "\n/router off", registry=reg(b), repo_config=self.CFG)
        self.assertEqual((plan.mode, plan.target), ("auto", "route"))

    def test_session_override_exposed_and_skips_no_route_heuristics(self):
        b = FakeBackend(level="L1")
        plan = route("/router session=frontier:high\nhello", registry=reg(b), repo_config=self.CFG)
        self.assertEqual(plan.target, "route")
        self.assertEqual(sp(plan).start, Profile("frontier", "high"))

    def test_session_override_keeps_risk_plan_first_and_review_floor(self):
        b = FakeBackend(level="L3")
        plan = route("/router session=economy:medium\nFix the auth token check in parser.py",
                     registry=reg(b), repo_config=self.CFG)
        self.assertEqual((sp(plan).start, sp(plan).plan_first, sp(plan).review),
                         (Profile("economy", "medium"), True, Profile("frontier", "high")))

    def test_typed_override_keeps_review_only_target(self):
        b = FakeBackend(level="L2")
        plan = route("/router session=frontier:xhigh\nreview my diff in foo.py",
                     registry=reg(b), repo_config=self.CFG)
        self.assertEqual(plan.target, "review_only")

    def test_backend_runtime_failure_recorded_in_default(self):
        b = FakeBackend("p", exc=KeyError("x"))
        plan = route(DEV, registry=reg(b), repo_config={"difficulty": {"backend": "p"}})
        self.assertEqual((plan.decision.backend, plan.decision.level), ("default", "L3"))
        self.assertEqual(plan.decision.reason_codes, ("p:KeyError",))

    def test_rejected_command_is_stripped_and_reported(self):
        b = FakeBackend()
        plan = route("/router bogus\n" + DEV, registry=reg(b), repo_config=self.CFG)
        self.assertTrue(plan.override_rejected)
        self.assertEqual(b.calls[0][0].task, DEV)
        self.assertFalse(route(DEV, registry=reg(b), repo_config=self.CFG).override_rejected)

    def test_manual_with_session_override_applies_risk_floors_without_classifying(self):
        b = FakeBackend()
        plan = route("/router manual session=economy:medium\nFix the data loss bug in parser.py",
                     registry=reg(b), repo_config=self.CFG)
        self.assertEqual((plan.mode, plan.target, plan.decision, b.calls), ("manual", "route", None, []))
        self.assertIn("data_loss", plan.risk_flags)
        self.assertEqual((sp(plan).start, sp(plan).plan_first), (Profile("economy", "medium"), True))

    def test_manual_without_overrides_is_no_route(self):
        b = FakeBackend()
        plan = route(DEV, registry=reg(b), repo_config={"router": {"mode": "manual"}, **self.CFG})
        self.assertEqual(plan.target, "no_route")
        self.assertEqual(b.calls, [])


if __name__ == "__main__":
    unittest.main()

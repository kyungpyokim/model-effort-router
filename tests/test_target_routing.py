import unittest

from model_effort_router.difficulty.decision import DifficultyDecision
from model_effort_router.policy.router import route
from tests.test_router import FakeBackend, reg

CFG = {"difficulty": {"backend": "fake"}}
DOCKER = "Bump the base image in the Dockerfile to python 3.12"  # rules: no code-context word -> no_route


class TargetBackend(FakeBackend):
    provides_target = True

    def __init__(self, target, usage=None, **kw):
        super().__init__(**kw)
        self.target, self.last_usage, self.calls_model = target, usage, usage is not None

    def classify(self, task, timeout_s):
        d = super().classify(task, timeout_s)
        return DifficultyDecision(d.level, d.backend, risk_flags=d.risk_flags, target=self.target)


class DecisionTargetTest(unittest.TestCase):
    def test_target_validated_and_kept(self):
        self.assertIsNone(DifficultyDecision("L1", "b").target)
        for t in ("route", "plan_only", "review_only", "no_route"):
            self.assertEqual(DifficultyDecision("L1", "b", target=t).with_risk_flags(["auth"]).target, t)
        with self.assertRaises(ValueError):
            DifficultyDecision("L1", "b", target="maybe")


class BackendTargetTest(unittest.TestCase):
    def test_backend_target_beats_the_rules_both_ways(self):
        b = TargetBackend("route")
        plan = route(DOCKER, registry=reg(b), repo_config=CFG)
        self.assertEqual((plan.target, plan.target_source, len(b.calls)), ("route", "backend", 1))
        self.assertEqual(plan.decision.level, "L3")
        plan = route("Fix the bug in parser.py", registry=reg(TargetBackend("no_route")), repo_config=CFG)
        self.assertEqual((plan.target, plan.target_source), ("no_route", "backend"))

    def test_plan_only_and_review_only_from_the_backend(self):
        for t in ("plan_only", "review_only"):
            self.assertEqual(route(DOCKER, registry=reg(TargetBackend(t)), repo_config=CFG).target, t)

    def test_backend_no_route_keeps_decision_and_classifier_usage_for_the_log(self):
        b = TargetBackend("no_route", usage={"input_tokens": 541, "output_tokens": 12})
        plan = route("What does parser.py do?", registry=reg(b), repo_config=CFG)
        self.assertEqual(plan.target, "no_route")
        self.assertEqual(plan.decision.backend, "fake")
        self.assertEqual((plan.classifier_usage["input_tokens"], plan.classifier_usage_missing), (541, False))

    def test_explicit_and_typed_session_override_force_route_but_keep_plan_only(self):
        self.assertEqual(route("hello", registry=reg(TargetBackend("no_route")), repo_config=CFG, explicit=True).target, "route")
        plan = route("/router session=frontier:high\nhello", registry=reg(TargetBackend("no_route")), repo_config=CFG)
        self.assertEqual(plan.target, "route")
        self.assertEqual(route("hello", registry=reg(TargetBackend("plan_only")), repo_config=CFG, explicit=True).target, "plan_only")

    def test_risk_flags_still_merged_when_backend_decides_target(self):
        plan = route("Fix the login auth check in the Dockerfile", registry=reg(TargetBackend("route")), repo_config=CFG)
        self.assertIn("auth", plan.risk_flags)


class FallbackToRulesTest(unittest.TestCase):
    def cfg(self):
        return {"difficulty": {"backend": "t", "fallback": "f"}}

    def test_decision_without_target_uses_rules(self):
        t, f = TargetBackend("route", exc=TimeoutError(), name="t"), FakeBackend("f", level="L2")
        plan = route("Fix the bug in parser.py", registry=reg(t, f), repo_config=self.cfg())
        self.assertEqual((plan.target, plan.target_source, plan.decision.backend), ("route", "rules", "f"))

    def test_failed_primary_lets_the_rules_gate_the_fallback(self):
        """Jev down (key, network, shape): chit-chat must not pay for a subscription fallback call."""
        t, f = TargetBackend("route", exc=TimeoutError(), name="t"), FakeBackend("f", level="L2")
        plan = route("hello there", registry=reg(t, f), repo_config=self.cfg())
        self.assertEqual((plan.target, plan.decision, f.calls), ("no_route", None, []))
        self.assertEqual(len(t.calls), 1)

    def test_failed_primary_is_not_called_twice_and_stays_visible(self):
        t, f = TargetBackend("route", exc=TimeoutError(), name="t"), FakeBackend("f", level="L2")
        plan = route("Fix the bug in parser.py", registry=reg(t, f), repo_config=self.cfg())
        self.assertEqual((len(t.calls), len(f.calls)), (1, 1))
        self.assertIn("fallback_cause:t:TimeoutError", plan.decision.reason_codes)

    def test_both_backends_failing_keeps_both_causes_in_the_log(self):
        """Jev without a key and a fallback that fails too: the log must still say why Jev did not decide."""
        t = TargetBackend("route", exc=TimeoutError(), name="t")
        f = FakeBackend("f", exc=RuntimeError())
        plan = route("Fix the bug in parser.py", registry=reg(t, f), repo_config=self.cfg())
        self.assertEqual((plan.decision.backend, plan.decision.reason_codes), ("default", ("t:TimeoutError", "f:RuntimeError")))

    def test_override_turning_backend_no_route_into_route_is_logged_as_override(self):
        t = TargetBackend("no_route", name="t")
        plan = route("/router session=frontier:high\nhello", registry=reg(t), repo_config={"difficulty": {"backend": "t"}})
        self.assertEqual((plan.target, plan.target_source), ("route", "override"))

    def test_default_decision_uses_rules(self):
        t = TargetBackend("route", exc=RuntimeError(), name="t")
        plan = route("Fix the bug in parser.py", registry=reg(t), repo_config={"difficulty": {"backend": "t"}})
        self.assertEqual((plan.decision.backend, plan.target, plan.target_source), ("default", "route", "rules"))


class UnchangedBehaviourTest(unittest.TestCase):
    def test_backend_without_target_keeps_rules_first_and_no_call_on_no_route(self):
        b = FakeBackend()
        plan = route(DOCKER, registry=reg(b), repo_config=CFG)
        self.assertEqual((plan.target, plan.target_source, b.calls), ("no_route", "rules", []))
        self.assertIsNone(plan.decision)

    def test_off_and_manual_never_call_the_backend(self):
        b = TargetBackend("route")
        self.assertEqual(route("/router off\n" + DOCKER, registry=reg(b), repo_config=CFG).target, "no_route")
        manual = {"router": {"mode": "manual"}, **CFG}
        self.assertEqual(route(DOCKER, registry=reg(b), repo_config=manual).target, "no_route")
        self.assertEqual(b.calls, [])


if __name__ == "__main__":
    unittest.main()

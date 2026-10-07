import math
import unittest
from dataclasses import FrozenInstanceError
from model_effort_router.difficulty.decision import DifficultyDecision, DifficultyInput, EFFORTS, ROLES, merge_risk_flags

class DecisionContractTest(unittest.TestCase):
    def test_all_roles_and_efforts_are_supported(self):
        for role in ROLES:
            for effort in EFFORTS:
                self.assertEqual(DifficultyDecision(role, effort, "fake").role, role)
    def test_invalid_values_and_non_finite_confidence_rejected(self):
        for role, effort, confidence in (("L3", "high", None), ("review", "L3", None),
                                         ("review", "high", True), ("analysis", "low", math.nan),
                                         ("analysis", "low", math.inf), ("fix", "medium", 1.1)):
            with self.subTest(role=role, effort=effort), self.assertRaises(ValueError):
                DifficultyDecision(role, effort, "fake", confidence)
    def test_target_is_optional_and_limited_to_route_or_no_route(self):
        self.assertIsNone(DifficultyDecision("fix", "low", "fake").target)
        for target in ("route", "no_route"):
            self.assertEqual(DifficultyDecision("fix", "low", "fake", target=target).target, target)
        with self.assertRaises(ValueError):
            DifficultyDecision("fix", "low", "fake", target="maybe")
    def test_decision_is_immutable_and_risk_flags_are_canonical(self):
        decision = DifficultyDecision("review", "high", "fake")
        with self.assertRaises(FrozenInstanceError):
            decision.effort = "low"
        self.assertEqual(merge_risk_flags(("payment", "auth"), ("security", "auth")), ("security", "auth", "payment"))
    def test_input_is_immutable_value(self):
        value = DifficultyInput("task", ("a.py",))
        self.assertEqual(value.paths, ("a.py",))

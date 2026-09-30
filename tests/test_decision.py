import dataclasses
import unittest

from model_effort_router.difficulty.decision import (
    RISK_FLAGS,
    DifficultyDecision,
)
from model_effort_router.profiles.profiles import EFFORTS, TIERS, Profile, parse_profile


class DecisionValidationTest(unittest.TestCase):
    def test_minimal_valid(self):
        d = DifficultyDecision(level="L3", backend="x")
        self.assertEqual(d.risk_flags, ())
        self.assertIsNone(d.confidence)

    def test_invalid_level(self):
        for bad in ("L0", "L6", "l3", "", None, 3):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                DifficultyDecision(level=bad, backend="x")

    def test_backend_required(self):
        for bad in ("", None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                DifficultyDecision(level="L1", backend=bad)

    def test_distribution_sum(self):
        ok = {"L1": 0.01, "L2": 0.07, "L3": 0.91, "L4": 0.01, "L5": 0.0}
        self.assertEqual(DifficultyDecision("L3", "x", distribution=ok).distribution["L3"], 0.91)
        with self.assertRaises(ValueError):
            DifficultyDecision("L3", "x", distribution={"L3": 0.5})

    def test_distribution_bad_key_or_value(self):
        with self.assertRaises(ValueError):
            DifficultyDecision("L3", "x", distribution={"L3": 0.5, "L9": 0.5})
        with self.assertRaises(ValueError):
            DifficultyDecision("L3", "x", distribution={"L3": 1.5, "L2": -0.5})

    def test_confidence_range(self):
        for bad in (-0.1, 1.1):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                DifficultyDecision("L3", "x", confidence=bad)

    def test_unknown_risk_flag(self):
        with self.assertRaises(ValueError):
            DifficultyDecision("L3", "x", risk_flags=("bogus",))

    def test_frozen(self):
        d = DifficultyDecision("L3", "x")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            d.level = "L4"

    def test_with_risk_flags_merges_in_canonical_order_without_duplicates(self):
        d = DifficultyDecision("L3", "x", risk_flags=("payment", "auth"))
        merged = d.with_risk_flags(("auth", "security"))
        self.assertEqual(merged.risk_flags, ("security", "auth", "payment"))
        self.assertEqual(d.risk_flags, ("payment", "auth"))  # original untouched
        self.assertTrue(set(merged.risk_flags) <= set(RISK_FLAGS))


class ProfileTest(unittest.TestCase):
    def test_ordering_data(self):
        self.assertEqual(TIERS, ("economy", "balanced", "frontier"))
        self.assertEqual(EFFORTS, ("medium", "high", "xhigh"))

    def test_parse_profile(self):
        self.assertEqual(parse_profile("frontier:high"), Profile("frontier", "high"))

    def test_parse_profile_invalid(self):
        for bad in ("frontier", "ultra:high", "frontier:low", "a:b:c", "", None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_profile(bad)

    def test_profile_validates_and_is_frozen(self):
        with self.assertRaises(ValueError):
            Profile("gold", "high")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            Profile("economy", "medium").tier = "frontier"

    def test_elementwise_max(self):
        self.assertEqual(
            Profile("economy", "xhigh").at_least(Profile("frontier", "high")),
            Profile("frontier", "xhigh"),
        )


if __name__ == "__main__":
    unittest.main()

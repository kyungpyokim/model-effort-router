import unittest

from model_effort_router.difficulty.decision import LEVELS, RISK_FLAGS, DifficultyDecision
from model_effort_router.policy.stages import (
    PromotionConfig,
    decide_manual,
    decide_stages,
    restrict_to_target,
)
from model_effort_router.profiles.profiles import EFFORTS, TIERS, Profile

E, B, F = "economy", "balanced", "frontier"

# Spec 11.1: level -> (plan, implement, review)
TABLE = {
    "L1": (None, (E, "medium"), (E, "medium")),
    "L2": (None, (E, "medium"), (F, "high")),
    "L3": ((F, "high"), (B, "high"), (F, "high")),
    "L4": ((F, "high"), (F, "high"), (F, "high")),
    "L5": ((F, "xhigh"), (F, "high"), (F, "xhigh")),
}


def dec(level, flags=(), backend="subscription", confidence=None):
    return DifficultyDecision(level=level, backend=backend, risk_flags=flags, confidence=confidence)


def prof(result):
    return {s.stage: (s.tier, s.effort) for s in result.stages if s.stage != "test_gate"}


def rank(p):
    return TIERS.index(p[0]), EFFORTS.index(p[1])


class LevelDefaultsTest(unittest.TestCase):
    def test_every_level_row(self):
        for level, (plan, impl, review) in TABLE.items():
            with self.subTest(level=level):
                r = decide_stages(dec(level))
                p = prof(r)
                self.assertEqual(p.get("plan"), plan)
                self.assertEqual(p["implement"], impl)
                self.assertEqual(p["review"], review)
                self.assertEqual(r.level, level)
                self.assertEqual(r.applied_rules, ("level_default",))

    def test_stage_order_and_test_gate(self):
        r = decide_stages(dec("L3"))
        self.assertEqual([s.stage for s in r.stages], ["plan", "implement", "test_gate", "review"])
        gate = r.stages[2]
        self.assertEqual((gate.tier, gate.effort), (None, None))
        self.assertEqual(
            [s.stage for s in decide_stages(dec("L1")).stages], ["implement", "test_gate", "review"]
        )

    def test_to_dict_matches_spec_shape(self):
        self.assertEqual(
            decide_stages(dec("L3", ("auth",))).to_dict(),
            {
                "level": "L3",
                "stages": [
                    {"stage": "plan", "tier": "frontier", "effort": "high"},
                    {"stage": "implement", "tier": "balanced", "effort": "high"},
                    {"stage": "test_gate"},
                    {"stage": "review", "tier": "frontier", "effort": "high"},
                ],
                "applied_rules": ["level_default", "risk_min:auth"],
            },
        )

    def test_deterministic(self):
        self.assertEqual(decide_stages(dec("L2", ("auth",))), decide_stages(dec("L2", ("auth",))))


class RiskMinimumsTest(unittest.TestCase):
    def test_security_auth_payment(self):
        for flag in ("security", "auth", "payment"):
            with self.subTest(flag=flag):
                p = prof(decide_stages(dec("L1", (flag,))))
                self.assertEqual(p["plan"], (F, "high"))
                self.assertEqual(p["implement"], (E, "medium"))  # implement untouched
                self.assertEqual(p["review"], (F, "high"))

    def test_data_flags_require_xhigh_review(self):
        for flag in ("data_migration", "data_loss"):
            for level in LEVELS:
                with self.subTest(flag=flag, level=level):
                    p = prof(decide_stages(dec(level, (flag,))))
                    self.assertEqual(p["review"], (F, "xhigh"))
                    self.assertGreaterEqual(rank(p["plan"]), (2, 1))

    def test_concurrency_review_only(self):
        p = prof(decide_stages(dec("L1", ("concurrency",))))
        self.assertNotIn("plan", p)
        self.assertEqual(p["review"], (F, "high"))

    def test_never_lower_any_stage(self):
        for level in LEVELS:
            base = prof(decide_stages(dec(level)))
            for flag in RISK_FLAGS:
                with self.subTest(level=level, flag=flag):
                    got = prof(decide_stages(dec(level, (flag,))))
                    for stage, value in base.items():
                        self.assertGreaterEqual(rank(got[stage]), rank(value), stage)

    def test_higher_defaults_are_kept(self):
        p = prof(decide_stages(dec("L5", ("auth", "data_loss"))))
        self.assertEqual(p["plan"], (F, "xhigh"))  # not lowered to high
        self.assertEqual(p["review"], (F, "xhigh"))
        self.assertEqual(p["implement"], (F, "high"))

    def test_l4_data_loss_raises_review_only(self):
        p = prof(decide_stages(dec("L4", ("data_loss",))))
        self.assertEqual(p["review"], (F, "xhigh"))
        self.assertEqual(p["plan"], (F, "high"))

    def test_applied_rules_recorded_even_when_no_change(self):
        r = decide_stages(dec("L3", ("concurrency", "auth")))
        self.assertEqual(r.applied_rules, ("level_default", "risk_min:auth", "risk_min:concurrency"))

    def test_default_backend_still_gets_minimums(self):
        d = dec("L3", ("data_loss",), backend="default")
        self.assertEqual(prof(decide_stages(d))["review"], (F, "xhigh"))


class PromotionTest(unittest.TestCase):
    ENABLED = PromotionConfig(enabled=True, thresholds={"subscription": 0.8})

    def test_disabled_by_default(self):
        self.assertEqual(decide_stages(dec("L3", confidence=0.1)).level, "L3")
        off = PromotionConfig(enabled=False, thresholds={"subscription": 0.8})
        self.assertEqual(decide_stages(dec("L3", confidence=0.1), promotion=off).level, "L3")

    def test_low_confidence_promotes_one_level(self):
        r = decide_stages(dec("L3", confidence=0.5), promotion=self.ENABLED)
        self.assertEqual(r.level, "L4")
        self.assertEqual(prof(r)["implement"], (F, "high"))
        self.assertIn("confidence_promotion:L3->L4", r.applied_rules)

    def test_no_promotion_cases(self):
        cases = [
            dec("L3", confidence=0.9),  # above threshold
            dec("L3", confidence=None),  # unknown confidence
            dec("L3", confidence=0.1, backend="other"),  # no calibrated threshold
            dec("L3", confidence=0.1, backend="default"),
        ]
        for d in cases:
            with self.subTest(d=d):
                r = decide_stages(d, promotion=self.ENABLED)
                self.assertEqual(r.level, "L3")
                self.assertEqual(r.applied_rules, ("level_default",))

    def test_l5_is_capped(self):
        r = decide_stages(dec("L5", confidence=0.1), promotion=self.ENABLED)
        self.assertEqual(r.level, "L5")


class ManualTest(unittest.TestCase):
    def test_order_test_gate_and_no_level(self):
        r = decide_manual(
            {"review": Profile(F, "high"), "plan": Profile(F, "high"), "implement": Profile(E, "medium")}, ()
        )
        self.assertIsNone(r.level)
        self.assertEqual([s.stage for s in r.stages], ["plan", "implement", "test_gate", "review"])
        self.assertEqual(r.applied_rules, ("override:review", "override:plan", "override:implement"))

    def test_no_test_gate_without_implement(self):
        r = decide_manual({"review": Profile(F, "high")}, ())
        self.assertEqual([s.stage for s in r.stages], ["review"])
        self.assertEqual(r.to_dict()["level"], None)

    def test_risk_floors_add_missing_stages(self):
        r = decide_manual({"implement": Profile(E, "medium")}, ("auth",))
        self.assertEqual(
            [(s.stage, s.tier, s.effort) for s in r.stages],
            [("plan", F, "high"), ("implement", E, "medium"), ("test_gate", None, None), ("review", F, "high")],
        )
        self.assertEqual(r.applied_rules, ("risk_min:auth", "override:implement"))

    def test_concurrency_floor_adds_only_review(self):
        r = decide_manual({}, ("concurrency",))
        self.assertEqual([s.stage for s in r.stages], ["review"])

    def test_risk_clamp_applies(self):
        r = decide_manual({"review": Profile(E, "medium")}, ("data_loss",))
        self.assertEqual(prof(r)["review"], (F, "xhigh"))
        self.assertIn("override_clamped:review", r.applied_rules)


class OverrideAndRestrictTest(unittest.TestCase):
    def test_override_replaces_stage_and_is_recorded(self):
        r = decide_stages(dec("L1"), overrides={"implement": Profile(F, "high")})
        self.assertEqual(prof(r)["implement"], (F, "high"))
        self.assertIn("override:implement", r.applied_rules)

    def test_override_beats_level_default(self):
        r = decide_stages(dec("L3"), overrides={"implement": Profile(E, "medium")})
        self.assertEqual(prof(r)["implement"], (E, "medium"))
        self.assertFalse([x for x in r.applied_rules if x.startswith("override_clamped")])

    def test_override_below_risk_minimum_is_clamped(self):
        r = decide_stages(dec("L3", ("data_loss",)), overrides={"review": Profile(E, "medium")})
        self.assertEqual(prof(r)["review"], (F, "xhigh"))
        self.assertIn("override:review", r.applied_rules)
        self.assertIn("override_clamped:review", r.applied_rules)

    def test_override_partially_below_minimum_is_raised_per_axis(self):
        r = decide_stages(dec("L1", ("data_loss",)), overrides={"review": Profile(E, "xhigh")})
        self.assertEqual(prof(r)["review"], (F, "xhigh"))

    def test_override_at_or_above_minimum_not_clamped(self):
        r = decide_stages(dec("L3", ("auth",)), overrides={"review": Profile(F, "xhigh")})
        self.assertEqual(prof(r)["review"], (F, "xhigh"))
        self.assertNotIn("override_clamped:review", r.applied_rules)

    def test_override_on_unconstrained_stage_not_clamped(self):
        r = decide_stages(dec("L3", ("auth",)), overrides={"implement": Profile(E, "medium")})
        self.assertEqual(prof(r)["implement"], (E, "medium"))

    def test_override_can_add_plan(self):
        r = decide_stages(dec("L1"), overrides={"plan": Profile(F, "xhigh")})
        self.assertEqual([s.stage for s in r.stages], ["plan", "implement", "test_gate", "review"])
        self.assertEqual(prof(r)["plan"], (F, "xhigh"))

    def test_restrict_plan_only(self):
        r = restrict_to_target(decide_stages(dec("L1")), "plan_only")
        self.assertEqual([s.stage for s in r.stages], ["plan"])
        self.assertEqual(prof(r)["plan"], (F, "high"))  # plan requested although L1 skips it
        self.assertIn("target:plan_only", r.applied_rules)
        r3 = restrict_to_target(decide_stages(dec("L5")), "plan_only")
        self.assertEqual(prof(r3)["plan"], (F, "xhigh"))

    def test_restrict_review_only(self):
        r = restrict_to_target(decide_stages(dec("L2")), "review_only")
        self.assertEqual([s.stage for s in r.stages], ["review"])
        self.assertEqual(prof(r)["review"], (F, "high"))

    def test_restrict_route_is_identity(self):
        r = decide_stages(dec("L3"))
        self.assertEqual(restrict_to_target(r, "route"), r)


if __name__ == "__main__":
    unittest.main()

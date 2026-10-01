import unittest

from model_effort_router.difficulty.decision import DifficultyDecision
from model_effort_router.policy.overrides import parse_override
from model_effort_router.policy.router import route
from model_effort_router.policy.session import session_plan
from model_effort_router.profiles.profiles import Profile
from tests.test_router import FakeBackend, reg

CFG = {"difficulty": {"backend": "fake"}}
E, B, F = "economy", "balanced", "frontier"
P = Profile


def dec(level, flags=()):
    return DifficultyDecision(level=level, backend="fake", risk_flags=tuple(flags))


# level -> (start, ladder, plan_first, review)  (spec 11.4)
TABLE = {
    "L1": (P(E, "medium"), (P(E, "high"), P(B, "high")), False, None),
    "L2": (P(E, "medium"), (P(B, "high"), P(F, "high")), False, None),
    "L3": (P(B, "high"), (P(F, "high"), P(F, "xhigh")), False, None),
    "L4": (P(F, "high"), (P(F, "xhigh"),), True, P(F, "high")),
    "L5": (P(F, "xhigh"), (), True, P(F, "xhigh")),
}


class TableTest(unittest.TestCase):
    def test_every_level_row(self):
        for level, (start, ladder, plan_first, review) in TABLE.items():
            with self.subTest(level=level):
                sp = session_plan(dec(level), (), None)
                self.assertEqual((sp.level, sp.start, sp.ladder, sp.plan_first, sp.review),
                                 (level, start, ladder, plan_first, review))
                self.assertEqual(sp.applied_rules, ("level_default",))

    def test_ladder_never_longer_than_two(self):
        for level in TABLE:
            self.assertLessEqual(len(session_plan(dec(level), (), None).ladder), 2)


class RiskTest(unittest.TestCase):
    def test_each_flag_forces_plan_first_and_review(self):
        for flag, review in (("security", P(F, "high")), ("auth", P(F, "high")), ("payment", P(F, "high")),
                             ("data_migration", P(F, "xhigh")), ("data_loss", P(F, "xhigh"))):
            with self.subTest(flag=flag):
                sp = session_plan(dec("L1"), (flag,), None)
                self.assertTrue(sp.plan_first)
                self.assertEqual(sp.review, review)
                self.assertIn(f"risk_min:{flag}", sp.applied_rules)
                self.assertEqual(sp.start, TABLE["L1"][0])  # risk never raises the start profile

    def test_concurrency_adds_review_but_not_plan(self):
        sp = session_plan(dec("L2"), ("concurrency",), None)
        self.assertEqual((sp.plan_first, sp.review), (False, P(F, "high")))

    def test_risk_floor_never_lowers_a_higher_review(self):
        self.assertEqual(session_plan(dec("L5"), ("auth",), None).review, P(F, "xhigh"))
        self.assertEqual(session_plan(dec("L4"), ("data_loss",), None).review, P(F, "xhigh"))

    def test_flags_come_from_decision_and_argument_merged(self):
        sp = session_plan(dec("L2", ["auth"]), ("concurrency",), None)
        self.assertTrue(sp.plan_first)
        self.assertEqual(sp.review, P(F, "high"))

    def test_plan_profile_respects_floor_and_level(self):
        self.assertEqual(session_plan(dec("L3"), (), None).plan_profile, P(F, "high"))
        self.assertEqual(session_plan(dec("L5"), (), None).plan_profile, P(F, "xhigh"))
        self.assertEqual(session_plan(dec("L1"), ("data_loss",), None).plan_profile, P(F, "high"))


class OverrideTest(unittest.TestCase):
    def test_override_replaces_start_and_keeps_only_higher_rungs(self):
        sp = session_plan(dec("L2"), (), {"session": P(B, "high")})
        self.assertEqual((sp.start, sp.ladder), (P(B, "high"), (P(F, "high"),)))
        self.assertIn("override:session", sp.applied_rules)
        self.assertNotIn("override_clamped:session", sp.applied_rules)

    def test_override_above_every_rung_has_no_ladder(self):
        self.assertEqual(session_plan(dec("L2"), (), {"session": P(F, "xhigh")}).ladder, ())

    def test_override_with_risk_keeps_plan_first_and_review_floor(self):
        # Same as the default path: risk never moves the session profile, only plan-first + review floor.
        sp = session_plan(dec("L2"), ("auth",), {"session": P(E, "medium")})
        self.assertEqual((sp.start, sp.plan_first, sp.review), (P(E, "medium"), True, P(F, "high")))
        self.assertEqual(sp.start, session_plan(dec("L1"), ("auth",), {"session": P(E, "medium")}).start)

    def test_override_never_clamped_without_risk(self):
        sp = session_plan(dec("L4"), (), {"session": P(E, "medium")})
        self.assertEqual(sp.start, P(E, "medium"))

    def test_manual_no_decision_uses_override_only(self):
        sp = session_plan(None, ("auth",), {"session": P(F, "xhigh")})
        self.assertEqual((sp.level, sp.start, sp.ladder, sp.plan_first, sp.review),
                         (None, P(F, "xhigh"), (), True, P(F, "high")))

    def test_no_decision_and_no_override_is_an_error(self):
        with self.assertRaises(ValueError):
            session_plan(None, (), None)


class OverrideParsingTest(unittest.TestCase):
    def test_session_token_parsed(self):
        o, rest = parse_override("/router session=frontier:high\nfix x")
        self.assertEqual((o.session, rest, o.rejected), (P(F, "high"), "fix x", False))
        self.assertFalse(o.is_empty)

    def test_session_combines_with_mode_and_rejects_bad_or_duplicate(self):
        self.assertEqual(parse_override("/router off")[0].mode, "off")
        for bad in ("/router session=frontier", "/router session=x:high", "/router session=frontier:high session=economy:medium"):
            self.assertTrue(parse_override(bad + "\nfix")[0].rejected, bad)

    def test_route_exposes_session_override_and_explicit_forces_route(self):
        registry = reg(FakeBackend(level="L2"))
        plan = route("/router session=frontier:high\nhello there", registry=registry, repo_config=CFG, explicit=True)
        self.assertEqual(plan.target, "route")
        self.assertEqual(plan.overrides["session"], P(F, "high"))
        self.assertEqual(route("hello there", registry=registry, repo_config=CFG).target, "no_route")
        self.assertEqual(route("hello there", registry=registry, repo_config=CFG, explicit=True).target, "route")

    def test_explicit_keeps_plan_only_and_off(self):
        registry = reg(FakeBackend(level="L2"))
        self.assertEqual(route("write a plan for the parser module", registry=registry, repo_config=CFG, explicit=True).target, "plan_only")
        self.assertEqual(route("/router off\nfix parser.py", registry=registry, repo_config=CFG, explicit=True).mode, "off")


if __name__ == "__main__":
    unittest.main()

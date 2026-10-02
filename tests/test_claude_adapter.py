import unittest

from model_effort_router.adapters.claude import HAIKU, ClaudeConfig, resolve
from model_effort_router.adapters.codex import resolve as codex_resolve
from model_effort_router.profiles.profiles import Profile


class ResolveTest(unittest.TestCase):
    def test_default_tiers_and_efforts(self):
        for tier, model in (("economy", "claude-sonnet-5-5"), ("balanced", "claude-sonnet-5-5"), ("frontier", "claude-opus-5-5")):
            for effort in ("medium", "high", "xhigh"):
                r = resolve(Profile(tier, effort))
                self.assertEqual((r.tier, r.model, r.requested_effort, r.applied_effort), (tier, model, effort, effort))

    def test_same_resolved_shape_as_codex(self):
        from dataclasses import fields
        names = lambda r: [f.name for f in fields(r)]
        self.assertEqual(names(resolve(Profile("economy", "medium"))), names(codex_resolve(Profile("economy", "medium"))))

    def test_model_without_supported_efforts_omits_the_effort(self):
        cfg = ClaudeConfig(tiers={"economy": HAIKU, "balanced": "claude-sonnet-5-5", "frontier": "claude-opus-5-5"})
        r = resolve(Profile("economy", "high"), cfg)
        self.assertEqual((r.model, r.requested_effort, r.applied_effort), (HAIKU, "high", None))

    def test_nearest_higher_supported_effort_else_highest(self):
        cfg = ClaudeConfig(model_efforts={"claude-sonnet-5-5": ("high", "max"), "claude-opus-5-5": ("low",), HAIKU: ()})
        self.assertEqual(resolve(Profile("balanced", "medium"), cfg).applied_effort, "high")
        self.assertEqual(resolve(Profile("frontier", "xhigh"), cfg).applied_effort, "low")
        self.assertEqual(resolve(Profile("balanced", "xhigh"), cfg).applied_effort, "max")

    def test_config_validation(self):
        with self.assertRaises(ValueError):
            ClaudeConfig(tiers={"economy": "x"})
        with self.assertRaises(ValueError):
            ClaudeConfig(tiers={"economy": "m", "balanced": "m", "frontier": "m"}, model_efforts={"other": ("low",)})
        with self.assertRaises(ValueError):
            ClaudeConfig(model_efforts={"claude-sonnet-5-5": ("ultra",), "claude-opus-5-5": (), HAIKU: ()})
        with self.assertRaises(ValueError):
            ClaudeConfig(efforts={"medium": "low", "high": "high", "xhigh": "ultra"})
        with self.assertRaises(ValueError):
            ClaudeConfig(model_efforts={"claude-sonnet-5-5": "high", "claude-opus-5-5": (), HAIKU: ()})


if __name__ == "__main__":
    unittest.main()

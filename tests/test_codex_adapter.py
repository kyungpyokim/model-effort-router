import unittest

from model_effort_router.adapters.codex import CodexConfig, resolve
from model_effort_router.profiles.profiles import Profile


class CodexAdapterTest(unittest.TestCase):
    def test_default_tier_models(self):
        self.assertEqual(resolve(Profile("economy", "medium")).model, "gpt-6-luna")
        self.assertEqual(resolve(Profile("balanced", "high")).model, "gpt-6-luna")
        self.assertEqual(resolve(Profile("frontier", "high")).model, "gpt-6-sol")

    def test_supported_effort_is_unchanged_and_both_reported(self):
        r = resolve(Profile("frontier", "xhigh"))
        self.assertEqual((r.tier, r.requested_effort, r.applied_effort), ("frontier", "xhigh", "xhigh"))

    def test_all_abstract_profiles_resolve_to_themselves_by_default(self):
        for tier in ("economy", "balanced", "frontier"):
            for effort in ("medium", "high", "xhigh"):
                with self.subTest(tier=tier, effort=effort):
                    self.assertEqual(resolve(Profile(tier, effort)).applied_effort, effort)

    def test_effort_map_is_data(self):
        cfg = CodexConfig(efforts={"medium": "medium", "high": "high", "xhigh": "ultra"})
        sol = resolve(Profile("frontier", "xhigh"), cfg)
        self.assertEqual((sol.requested_effort, sol.applied_effort), ("ultra", "ultra"))
        # luna does not support ultra and nothing is higher -> max supported
        luna = resolve(Profile("economy", "xhigh"), cfg)
        self.assertEqual((luna.requested_effort, luna.applied_effort), ("ultra", "max"))

    def test_unsupported_maps_to_nearest_higher(self):
        cfg = CodexConfig(
            tiers={"economy": "m", "balanced": "m", "frontier": "m"},
            model_efforts={"m": ("low", "high", "max")},
        )
        r = resolve(Profile("economy", "medium"), cfg)
        self.assertEqual((r.requested_effort, r.applied_effort), ("medium", "high"))
        r = resolve(Profile("economy", "xhigh"), cfg)
        self.assertEqual(r.applied_effort, "max")  # nearest higher than xhigh

    def test_no_higher_uses_max_supported(self):
        cfg = CodexConfig(
            tiers={"economy": "m", "balanced": "m", "frontier": "m"},
            model_efforts={"m": ("low", "medium", "high")},
        )
        r = resolve(Profile("frontier", "xhigh"), cfg)
        self.assertEqual((r.requested_effort, r.applied_effort), ("xhigh", "high"))

    def test_model_name_configurable(self):
        cfg = CodexConfig(tiers={"economy": "a", "balanced": "b", "frontier": "c"},
                          model_efforts={"a": ("medium",), "b": ("high",), "c": ("xhigh",)})
        self.assertEqual(resolve(Profile("balanced", "medium"), cfg).model, "b")
        self.assertEqual(resolve(Profile("balanced", "medium"), cfg).applied_effort, "high")

    def test_invalid_config_rejected_at_construction(self):
        T = {"economy": "m", "balanced": "m", "frontier": "m"}
        bad = [
            {"tiers": T},  # model without supported-effort data
            {"tiers": T, "model_efforts": {"m": ()}},  # empty
            {"tiers": T, "model_efforts": {"m": ("turbo",)}},  # unknown effort
            {"tiers": T, "model_efforts": {"m": "high"}},  # not a sequence of names
            {"tiers": {"economy": "m"}, "model_efforts": {"m": ("high",)}},  # missing tier
            {"efforts": {"medium": "medium", "high": "high"}},  # missing abstract effort
            {"efforts": {"medium": "medium", "high": "high", "xhigh": "turbo"}},
        ]
        for kwargs in bad:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                CodexConfig(**kwargs)

    def test_default_model_efforts_from_spike(self):
        cfg = CodexConfig()
        luna = cfg.model_efforts["gpt-6-luna"]
        self.assertEqual(luna, ("low", "medium", "high", "xhigh", "max"))
        for m in ("gpt-6-sol", "gpt-6.1-sol"):
            self.assertEqual(cfg.model_efforts[m], luna + ("ultra",))


if __name__ == "__main__":
    unittest.main()

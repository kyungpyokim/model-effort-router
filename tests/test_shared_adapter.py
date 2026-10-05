import unittest
from dataclasses import FrozenInstanceError
from itertools import combinations

from model_effort_router.adapters import antigravity, claude, codex
from model_effort_router.host import antigravity_exec, claude_exec, codex_exec
from model_effort_router.profiles.profiles import Profile


class SharedAdapterTest(unittest.TestCase):
    def test_all_hosts_return_the_same_immutable_profile_type(self):
        profiles = [adapter.resolve(Profile("economy", "medium"))
                    for adapter in (codex, claude, antigravity)]
        for profile in profiles:
            self.assertIs(type(profile), type(profiles[0]))
            with self.assertRaises(FrozenInstanceError):
                profile.model = "changed"

    def test_support_fallback_keeps_nearest_higher_or_highest_for_every_effort(self):
        order = ("low", "medium", "high", "xhigh", "max", "ultra")
        self.assertEqual(codex.EFFORT_ORDER, order)
        for count in range(1, len(order) + 1):
            for supported in combinations(order, count):
                for requested in order:
                    expected = next((effort for effort in supported
                                     if order.index(effort) >= order.index(requested)), supported[-1])
                    with self.subTest(requested=requested, supported=supported):
                        self.assertEqual(codex._apply_support(requested, tuple(reversed(supported))), expected)

    def test_all_hosts_share_guard_without_mutating_input(self):
        base = {"A": "1", "MER_CLASSIFIER": "0"}
        for executor in (codex_exec, claude_exec, antigravity_exec):
            self.assertIs(executor.session_env, codex_exec.session_env)
            result = executor.session_env(base)
            self.assertEqual(result, {"A": "1", "MER_CLASSIFIER": "1"})
            self.assertIsNot(result, base)
        self.assertEqual(base, {"A": "1", "MER_CLASSIFIER": "0"})

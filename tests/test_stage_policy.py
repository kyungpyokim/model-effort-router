"""The route JSON's stage_policy block: an explicit projection of the resolved route.

These tests pin two things: the projection agrees with the steps and pipeline the route already
resolved (it must never become a second source of truth), and it is additive, so a v7 route file
without it still replays.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import router  # noqa: E402

CONFIG = router.load_config(ROOT / "config" / "model-map.json")

TRIVIAL_FACTS = dict(router.TRIVIAL_EDIT_FACTS)


def payload_for(platform="codex", task_type="implementation", level="L3", tier=None, facts=None, check_available=False):
    classification = router.pinned_classification(task_type, level)
    if facts:
        classification = __import__("dataclasses").replace(classification, facts=dict(facts))
    result = router.route(
        "fix the parser bug in parser.py", platform, CONFIG,
        classifier=lambda _: classification, critical=tier == "critical", check_available=check_available,
    )
    commands_for = router.stage_commands(result, "fix the parser bug in parser.py")
    return result, json.loads(json.dumps(router.result_payload(result, commands_for, "fix the parser bug in parser.py")))


class StagePolicyProjectionTests(unittest.TestCase):
    CASES = (
        ("codex", "implementation", "L3"),
        ("codex", "implementation", "L5"),
        ("codex", "architectural_refactoring", "L2"),
        ("codex", "local_refactoring", "L4"),
        ("claude-code", "implementation", "L4"),
        ("claude-code", "architectural_refactoring", "L5"),
        ("antigravity", "implementation", "L3"),
        ("antigravity", "local_refactoring", "L5"),
        ("codex", "design", "L4"),
        ("codex", "review", "L2"),
        ("codex", "inspect", "L1"),
    )

    def test_the_projection_agrees_with_the_resolved_route(self):
        for platform, task_type, level in self.CASES:
            with self.subTest(platform=platform, task_type=task_type, level=level):
                _, payload = payload_for(platform, task_type, level)
                policy, steps = payload["stage_policy"], payload["steps"]
                # Every route has exactly one execute step; `role` carries the resolved role, which
                # is what tells a read-only row's executor apart from an implementer.
                self.assertTrue(policy["implement"]["enabled"])
                self.assertEqual(policy["implement"]["step"], steps[-1]["id"])
                self.assertEqual(policy["implement"]["model"], steps[-1]["model"])
                self.assertEqual(policy["implement"]["effort"], steps[-1]["effort"])
                self.assertEqual(policy["implement"]["role"], steps[-1]["role"])
                if policy["plan"]["enabled"]:
                    self.assertEqual(payload["mode"], "two_stage")
                    self.assertEqual((policy["plan"]["model"], policy["plan"]["effort"]), (steps[0]["model"], steps[0]["effort"]))
                    self.assertEqual(policy["plan"]["step"], steps[0]["id"])
                    self.assertEqual(policy["plan"]["role"], steps[0]["role"])
                else:
                    self.assertEqual(payload["mode"], "single")
                review = (payload["pipeline"] or {}).get("review")
                self.assertEqual(policy["review"]["enabled"], review is not None)
                if review:
                    self.assertEqual((policy["review"]["model"], policy["review"]["effort"]), (review["model"], review["effort"]))

    def test_the_test_stage_is_the_launcher_and_never_a_model(self):
        for platform, task_type, level in self.CASES:
            with self.subTest(task_type=task_type):
                _, payload = payload_for(platform, task_type, level)
                entry = payload["stage_policy"]["test"]
                if task_type in router.CODE_CHANGE_TASK_TYPES:
                    self.assertEqual(entry, {"enabled": True, "runner": "launcher", "model": None, "commands": "caller-supplied"})
                else:
                    self.assertEqual(entry, {"enabled": False, "reason": "read-only route"})

    def test_a_disabled_stage_carries_a_reason_and_no_model(self):
        _, payload = payload_for("codex", "inspect", "L1")
        for name in ("plan", "test", "review"):
            with self.subTest(stage=name):
                self.assertEqual(set(payload["stage_policy"][name]), {"enabled", "reason"})

    def test_a_skipped_stage_is_disabled_with_its_reason_not_missing(self):
        _, payload = payload_for("codex", "inspect", "L1")
        self.assertEqual(
            [(name, payload["stage_policy"][name]["reason"]) for name in ("plan", "test", "review")],
            [("plan", "read-only route"), ("test", "read-only route"), ("review", "read-only route")],
        )

    def test_a_trivial_edit_disables_plan_and_review_but_not_the_test_gate(self):
        _, payload = payload_for("codex", "implementation", "L1", facts=TRIVIAL_FACTS, check_available=True)
        self.assertEqual(payload["fast_path"], "trivial_edit")
        policy = payload["stage_policy"]
        self.assertFalse(policy["plan"]["enabled"])
        self.assertFalse(policy["review"]["enabled"])
        self.assertEqual(policy["plan"]["reason"], "trivial_edit fast path")
        self.assertTrue(policy["test"]["enabled"])

    def test_a_tier_only_changes_the_stages_it_names(self):
        _, plain = payload_for("codex", "implementation", "L5")
        _, critical = payload_for("codex", "implementation", "L5", tier="critical")
        self.assertEqual(plain["stage_policy"]["implement"], critical["stage_policy"]["implement"])
        self.assertEqual(critical["stage_policy"]["review"]["effort"], "max")
        self.assertEqual(critical["stage_policy"]["plan"]["effort"], "max")

    def test_the_projection_carries_the_ambiguity_gate(self):
        _, payload = payload_for("codex", "implementation", "L4")
        self.assertEqual(payload["stage_policy"]["ambiguity"], payload["ambiguity"])

    def test_the_block_is_additive_for_route_file_replay(self):
        _, payload = payload_for("codex", "implementation", "L4")
        self.assertIn("stage_policy", payload)
        payload.pop("stage_policy")
        router.validated_commands(payload)  # a v7 file written before the field still replays
        _, with_block = payload_for("codex", "implementation", "L4")
        router.validated_commands(with_block)


if __name__ == "__main__":
    unittest.main()

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import router  # noqa: E402

CONFIG = router.load_config(ROOT / "config" / "model-map.json")
BASE_FACTS = {
    "mechanical_only": "no", "files_touched": "1", "crosses_module_boundary": "no", "crosses_service_boundary": "no",
    "fix_or_result_known": "yes", "intermittent_or_concurrency": "no", "needs_new_structure": "no",
    "changes_security_or_payment_logic": "no", "reviews_security_sensitive_code": "no", "security_domain": "none",
    "changes_public_api_contract": "no", "changes_persisted_data": "no", "irreversible_or_ledger_or_crypto": "no",
    "changes_trust_boundary": "no", "blast_radius": "narrow", "silent_failure_material_harm": "no",
}


def routed(platform, task_type="implementation", understanding="yes", level=None, config=CONFIG, **facts):
    all_facts = {**BASE_FACTS, **facts}
    if understanding is not None:
        all_facts["requires_code_understanding"] = understanding
    level_, tier, matched, needs_context = router.evaluate_rules({**router.OPTIONAL_FACT_DEFAULTS, **all_facts})
    classification = router.Classification(
        task_type=task_type, level=level_, risk_flags={f: False for f in router.RISK_FLAGS}, reason="r", source="primary",
        facts=all_facts, matched_rules=tuple(matched), risk_tier=tier, needs_context=needs_context,
    )
    return router.route("t", platform, config, explicit_level=level, classifier=lambda _: classification)


class L2RefinementTests(unittest.TestCase):
    def profile(self, result):
        return result.model, result.effort

    def test_codex_l2_with_code_understanding_uses_luna_high(self):
        for task_type in ("implementation", "local_refactoring"):
            with self.subTest(task_type=task_type):
                result = routed("codex", task_type, "yes")
                self.assertEqual((result.level, self.profile(result)), ("L2", ("gpt-5.6-luna", "high")))
                self.assertTrue(any("requires_code_understanding=yes" in line for line in result.rationale))

    def test_claude_l2_with_code_understanding_uses_sonnet_low(self):
        for task_type in ("implementation", "local_refactoring"):
            with self.subTest(task_type=task_type):
                result = routed("claude-code", task_type, "yes")
                self.assertEqual((result.level, self.profile(result)), ("L2", ("claude-sonnet-5", "low")))

    def test_without_understanding_or_when_unknown_l2_keeps_the_cheap_profile(self):
        for understanding in ("no", "unknown", None):
            with self.subTest(understanding=understanding):
                self.assertEqual(self.profile(routed("codex", understanding=understanding)), ("gpt-5.6-luna", "medium"))
                self.assertEqual(self.profile(routed("claude-code", understanding=understanding))[0], "claude-haiku-4-5")

    def test_the_fact_never_changes_the_level_or_other_rungs(self):
        for platform, l3, l4 in (("codex", ("gpt-5.6-terra", "medium"), ("gpt-5.6-terra", "high")),
                                 ("claude-code", ("claude-sonnet-5", "medium"), ("claude-sonnet-5", "high"))):
            with self.subTest(platform=platform):
                self.assertEqual(self.profile(routed(platform, files_touched="2-5")), l3)
                self.assertEqual(routed(platform, files_touched="2-5").level, "L3")
                self.assertEqual(self.profile(routed(platform, crosses_module_boundary="yes")), l4)
                self.assertEqual(routed(platform, mechanical_only="yes", understanding="yes").level, "L1")
                self.assertNotEqual(routed(platform, mechanical_only="yes", understanding="yes").effort, "high")

    def test_only_single_stage_code_change_routes_are_refined(self):
        for task_type in ("design", "review"):
            with self.subTest(task_type=task_type):
                self.assertEqual(self.profile(routed("codex", task_type, "yes")), self.profile(routed("codex", task_type, "no")))
        arch = routed("codex", "architectural_refactoring", "yes")
        self.assertEqual(self.profile(arch), self.profile(routed("codex", "architectural_refactoring", "no")))
        l5 = routed("codex", understanding="yes", needs_new_structure="yes")
        self.assertEqual((l5.level, l5.mode), ("L5", "two_stage"))

    def test_antigravity_has_no_refinement(self):
        self.assertEqual(self.profile(routed("antigravity", understanding="yes")), self.profile(routed("antigravity", understanding="no")))

    def test_the_claude_command_carries_the_refined_effort(self):
        result = routed("claude-code", understanding="yes")
        command = router.stage_commands(result, "t")[0]
        self.assertEqual(command[command.index("--effort") + 1], "low")
        self.assertEqual(command[command.index("--permission-mode") + 1], "acceptEdits")

    def test_an_omitted_fact_defaults_to_unknown_in_classifier_output(self):
        payload = {"task_type": "implementation", "facts": dict(BASE_FACTS), "delegability": 0, "evidence": [], "reason": "r"}
        self.assertEqual(router.validate_classifier_output(payload).facts["requires_code_understanding"], "unknown")
        payload["facts"]["requires_code_understanding"] = "yes"
        self.assertEqual(router.validate_classifier_output(payload).facts["requires_code_understanding"], "yes")
        payload["facts"]["requires_code_understanding"] = "maybe"
        with self.assertRaises(ValueError):
            router.validate_classifier_output(payload)
        payload["facts"].pop("requires_code_understanding")
        payload["facts"]["surprise"] = "no"
        with self.assertRaises(ValueError):
            router.validate_classifier_output(payload)

    def test_the_classifier_is_asked_for_the_fact(self):
        self.assertIn("requires_code_understanding", router.CLASSIFIER_SCHEMA["properties"]["facts"]["required"])
        self.assertIn("- requires_code_understanding:", router.CLASSIFIER_PROMPT)
        schema = json.loads((ROOT / "config" / "classification-schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema, router.CLASSIFIER_SCHEMA)

    def test_invalid_refinements_are_rejected(self):
        good = CONFIG["platforms"]["codex"]["refinements"][0]
        for name, mutate in {
            "level": lambda r: r.update(level="L9"),
            "fact": lambda r: r.update(when={"nonsense": "yes"}),
            "value": lambda r: r.update(when={"requires_code_understanding": "maybe"}),
            "empty when": lambda r: r.update(when={}),
            "task type": lambda r: r.update(task_types=["design"]),
            "stage": lambda r: r.update(stage={"model": "x"}),
        }.items():
            with self.subTest(name=name):
                config = copy.deepcopy(CONFIG)
                mutate(config["platforms"]["codex"]["refinements"][0])
                with self.assertRaises(ValueError):
                    router.load_refinements(config, "codex")
        self.assertEqual(router.load_refinements(CONFIG, "codex"), [good])

    def test_a_config_without_refinements_still_routes(self):
        config = copy.deepcopy(CONFIG)
        del config["platforms"]["codex"]["refinements"]
        self.assertEqual(self.profile(routed("codex", understanding="yes", config=config)), ("gpt-5.6-luna", "medium"))

    def test_the_refined_rung_respects_the_effort_ceilings(self):
        for platform, allowed in (("codex", {"low", "medium", "high"}), ("claude-code", {"low", "medium", "high"})):
            for ref in CONFIG["platforms"][platform]["refinements"]:
                self.assertIn(ref["stage"]["effort"], allowed)
                self.assertNotIn("sol", ref["stage"]["model"])
                self.assertNotIn("opus", ref["stage"]["model"])


if __name__ == "__main__":
    unittest.main()

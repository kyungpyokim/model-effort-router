import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import router  # noqa: E402
from test_l2_refinement import routed  # noqa: E402

CONFIG = router.load_config(ROOT / "config" / "model-map.json")
LUNA, HAIKU = "gpt-5.6-luna", "claude-haiku-4-5"


class InspectTaskTypeTests(unittest.TestCase):
    def test_inspect_is_a_read_only_task_type(self):
        self.assertIn("inspect", router.TASK_TYPES)
        self.assertNotIn("inspect", router.CODE_CHANGE_TASK_TYPES)

    def test_every_platform_has_a_complete_cheap_inspect_row(self):
        expected = {"codex": (LUNA, "low"), "claude-code": (HAIKU, None)}
        for platform, profile in expected.items():
            matrix = router.load_matrix(CONFIG, platform)
            for level in router.LEVELS:
                with self.subTest(platform=platform, level=level):
                    entry = matrix["inspect"][level]
                    self.assertEqual((entry["model"], entry["effort"]), profile)
        antigravity = router.load_matrix(CONFIG, "antigravity")
        for level in router.LEVELS:
            self.assertEqual(antigravity["inspect"][level], antigravity["review"]["L1"])

    def test_the_classifier_accepts_inspect_with_zero_files(self):
        payload = {
            "task_type": "inspect",
            "facts": {
                "mechanical_only": "no", "files_touched": "0", "crosses_module_boundary": "no",
                "crosses_service_boundary": "no", "fix_or_result_known": "yes", "intermittent_or_concurrency": "no",
                "needs_new_structure": "no", "changes_security_or_payment_logic": "no",
                "reviews_security_sensitive_code": "no", "security_domain": "none", "changes_public_api_contract": "no",
                "changes_persisted_data": "no", "irreversible_or_ledger_or_crypto": "no", "changes_trust_boundary": "no",
                "blast_radius": "narrow", "silent_failure_material_harm": "no", "requires_code_understanding": "no",
            },
            "delegability": 0, "evidence": [], "reason": "explain a function",
        }
        result = router.validate_classifier_output(payload)
        self.assertEqual((result.task_type, result.level), ("inspect", "L2"))
        payload["task_type"] = "implementation"
        with self.assertRaises(ValueError):
            router.validate_classifier_output(payload)  # zero files is still invalid for a code change

    def test_the_classifier_prompt_explains_inspect_and_its_boundary(self):
        self.assertIn("- inspect:", router.CLASSIFIER_PROMPT)
        self.assertIn("never widen", router.CLASSIFIER_PROMPT)


def profiles(result):
    """Every (model, effort) a route or its pipeline would run."""
    found = {(result.model, result.effort)} | {(s["model"], s["effort"]) for s in result.stages}
    for role in ("review", "replan"):
        if result.pipeline and result.pipeline[role]:
            found.add((result.pipeline[role]["model"], result.pipeline[role]["effort"]))
    return found


class InspectRoutingTests(unittest.TestCase):
    def test_a_standard_l1_l2_inspect_is_a_single_cheap_read_only_route(self):
        for platform, profile in (("codex", (LUNA, "low")), ("claude-code", (HAIKU, None))):
            with self.subTest(platform=platform):
                result = routed(platform, "inspect", None, files_touched="0")
                self.assertEqual((result.task_type, result.mode, result.fast_path), ("inspect", "single", "inspect"))
                self.assertEqual((result.model, result.effort), profile)
                self.assertIsNone(result.pipeline)
                self.assertIsNone(result.plan_dir)

    def test_inspect_is_promoted_to_review_when_it_turns_out_to_need_judgement(self):
        cases = (
            {"reviews_security_sensitive_code": "yes"},   # security review -> L4+
            {"fix_or_result_known": "no"},                # an open investigation -> L3
            {"crosses_module_boundary": "yes"},           # broad reach -> L4
            {"irreversible_or_ledger_or_crypto": "yes"},  # critical tier
        )
        for facts in cases:
            with self.subTest(facts=facts):
                result = routed("codex", "inspect", None, files_touched="0", **facts)
                self.assertEqual(result.task_type, "review")
                self.assertIsNone(result.fast_path)
                self.assertTrue(any("inspect" in line and "review" in line for line in result.rationale))

    def test_a_pinned_inspect_at_a_high_level_is_promoted_too(self):
        result = routed("claude-code", "inspect", None, level="L4", files_touched="0")
        self.assertEqual((result.task_type, result.fast_path), ("review", None))

    def test_a_critical_tier_inspect_becomes_a_judge_review_never_a_cheap_route_with_effort(self):
        for platform in ("codex", "claude-code", "antigravity"):
            judge = router.route("t", platform, CONFIG, explicit_task_type="review", critical=True)
            by_flag = router.route("t", platform, CONFIG, explicit_task_type="inspect", critical=True)
            by_fact = routed(platform, "inspect", None, files_touched="0", irreversible_or_ledger_or_crypto="yes")
            for how, result in (("critical=True", by_flag), ("fact", by_fact)):
                with self.subTest(platform=platform, how=how):
                    self.assertEqual((result.task_type, result.risk_tier, result.fast_path), ("review", "critical", None))
                    self.assertEqual(result.stages, judge.stages)
                    self.assertEqual((result.model, result.effort), (judge.model, judge.effort))
                    self.assertNotIn(HAIKU, {model for model, _ in profiles(result)})
                    self.assertFalse(any(model == LUNA and effort is None for model, effort in profiles(result)))

    def test_claude_haiku_never_carries_an_effort_on_any_route(self):
        for task_type in router.TASK_TYPES:
            for level in router.LEVELS:
                for critical in (False, True):
                    with self.subTest(task_type=task_type, level=level, critical=critical):
                        result = router.route(
                            "t", "claude-code", CONFIG, explicit_level=level, explicit_task_type=task_type, critical=critical
                        )
                        for model, effort in profiles(result):
                            if model == HAIKU:
                                self.assertIsNone(effort)

    def test_the_payload_carries_the_fast_path(self):
        result = routed("codex", "inspect", None, files_touched="0")
        payload = router.result_payload(result, router.stage_commands(result, "t"), "t")
        self.assertEqual(payload["fast_path"], "inspect")
        self.assertEqual(payload["schema_version"], 6)


class TrivialEditGateTests(unittest.TestCase):
    def test_fast_path_for_requires_every_condition(self):
        ok = dict(task_type="implementation", level="L1", risk_tier="standard",
                  facts={"requires_code_understanding": "no"}, check_available=True)
        self.assertEqual(router.fast_path_for(**ok), "trivial_edit")
        for name, value in (
            ("task_type", "architectural_refactoring"), ("task_type", "design"), ("level", "L2"),
            ("risk_tier", "elevated"), ("check_available", False),
            ("facts", {"requires_code_understanding": "yes"}),
            ("facts", {"requires_code_understanding": "unknown"}),
            ("facts", {}),
        ):
            with self.subTest(**{name: value}):
                self.assertIsNone(router.fast_path_for(**{**ok, name: value}))

    def test_a_mechanical_edit_with_a_check_is_fast_and_single_stage(self):
        # Codex L1 becomes Luna Medium only in Task 5 (config change); until then it is Luna Low.
        for platform, profile in (("codex", (LUNA, "low")), ("claude-code", (HAIKU, None))):
            with self.subTest(platform=platform):
                result = routed(platform, "implementation", "no", check_available=True, mechanical_only="yes")
                self.assertEqual((result.level, result.mode, result.fast_path), ("L1", "single", "trivial_edit"))
                self.assertEqual((result.model, result.effort), profile)
                self.assertEqual(result.pipeline["review"], None)
                self.assertEqual(result.pipeline["replan"], None)
                # Discriminating: the identical classification without a check gets the regular workflow (see
                # RegularWorkflowForNonFastL1Tests.test_the_same_classification_is_fast_only_with_a_deterministic_check).
                self.assertIsNotNone(routed(platform, "implementation", "no", mechanical_only="yes").pipeline["review"])


class RegularWorkflowForNonFastL1Tests(unittest.TestCase):
    def test_a_mechanical_edit_that_is_not_fast_gets_the_full_workflow(self):
        cases = (
            dict(understanding="no", check_available=False),   # no deterministic check configured
            dict(understanding="yes", check_available=True),   # needs code understanding
            dict(understanding="unknown", check_available=True),
            dict(understanding=None, check_available=True),
        )
        for platform, judge, implementer in (
            ("codex", ("gpt-5.6-sol", "high"), LUNA),
            ("claude-code", ("claude-opus-5", "high"), HAIKU),
        ):
            for case in cases:
                with self.subTest(platform=platform, **case):
                    result = routed(platform, "implementation", mechanical_only="yes", **case)
                    self.assertEqual((result.level, result.mode, result.fast_path), ("L1", "two_stage", None))
                    self.assertEqual([s["role"] for s in result.stages], ["planner", "implementer"])
                    self.assertEqual((result.stages[0]["model"], result.stages[0]["effort"]), judge)
                    self.assertEqual(result.stages[1]["model"], implementer)
                    self.assertEqual(result.pipeline["review"]["model"], judge[0])
                    self.assertEqual(result.pipeline["replan"]["model"], judge[0])

    def test_the_regular_workflow_judge_row_never_drops_below_l2(self):
        self.assertEqual(router.WORKFLOW_MIN_LEVEL, "L2")
        self.assertFalse(hasattr(router, "REVIEW_MIN_LEVEL"))
        self.assertFalse(hasattr(router, "PLAN_MIN_LEVEL"))

    def test_read_only_types_still_have_no_pipeline(self):
        for task_type in ("design", "review", "inspect"):
            with self.subTest(task_type=task_type):
                self.assertIsNone(routed("codex", task_type, None, files_touched="0").pipeline)

    def test_the_same_classification_is_fast_only_with_a_deterministic_check(self):
        for platform in ("codex", "claude-code"):
            fast = routed(platform, "implementation", "no", check_available=True, mechanical_only="yes")
            regular = routed(platform, "implementation", "no", check_available=False, mechanical_only="yes")
            with self.subTest(platform=platform):
                self.assertEqual((fast.fast_path, fast.mode, fast.pipeline["review"]), ("trivial_edit", "single", None))
                self.assertIsNotNone(regular.pipeline["review"])
                self.assertIsNotNone(regular.pipeline["replan"])
                self.assertEqual(regular.mode, "two_stage")

    def test_a_single_stage_l1_route_with_the_judge_as_implementer_still_reviews(self):
        # Phase 1 exception: a planner equal to the implementer is not inserted, but the review still runs.
        result = routed("codex", "architectural_refactoring", "no", level="L2")
        self.assertEqual(result.mode, "single")
        self.assertIsNotNone(result.pipeline["review"])


class InspectReuseTests(unittest.TestCase):
    def test_a_stored_inspect_route_is_not_reused_for_a_modify_request(self):
        with tempfile.TemporaryDirectory() as state, mock.patch.dict(os.environ, {"MODEL_EFFORT_ROUTER_STATE_DIR": state}):
            os.environ.pop("MODEL_EFFORT_ROUTER_SESSION", None)
            result = routed("codex", "inspect", None, files_touched="0")
            router.route_reuse.save_record("s", os.getcwd(), router.session_record(result, 0))
            reused, _, reason = router.load_reused_classification("s", os.getcwd(), "what does the router do")
            self.assertIsNotNone(reused)
            blocked, _, reason = router.load_reused_classification("s", os.getcwd(), "fix the bug in the router")
            self.assertIsNone(blocked)
            self.assertIn("operation changed", reason)

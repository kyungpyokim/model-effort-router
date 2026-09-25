import contextlib
import io
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

SOL, OPUS = "gpt-6-sol", "claude-opus-5-5"


def profile(stage):
    return stage["model"], stage["effort"]


class PlanWorkflowTests(unittest.TestCase):
    def test_l2_to_l4_code_changes_plan_with_the_judge_and_implement_cheaply(self):
        cases = (
            ("codex", "L2", {}, (SOL, "high"), ("gpt-6-luna", "high")),
            ("codex", "L3", {"files_touched": "2-5"}, (SOL, "high"), ("gpt-5.6-terra", "medium")),
            ("codex", "L4", {"crosses_module_boundary": "yes"}, (SOL, "high"), ("gpt-5.6-terra", "high")),
            ("claude-code", "L3", {"files_touched": "2-5"}, (OPUS, "high"), ("claude-sonnet-5", "medium")),
            ("claude-code", "L4", {"crosses_module_boundary": "yes"}, (OPUS, "high"), ("claude-sonnet-5", "high")),
        )
        for platform, level, facts, planner, implementer in cases:
            with self.subTest(platform=platform, level=level):
                result = routed(platform, understanding="yes", **facts)
                self.assertEqual((result.level, result.mode), (level, "two_stage"))
                self.assertEqual([s["role"] for s in result.stages], ["planner", "implementer"])
                self.assertEqual(profile(result.stages[0]), planner)
                self.assertEqual(profile(result.stages[1]), implementer)
                self.assertTrue(result.plan_dir)
                self.assertEqual(result.pipeline["review"]["model"], planner[0])
                self.assertEqual(result.pipeline["replan"]["model"], planner[0])

    def test_the_l2_refinement_still_picks_the_implementer_rung(self):
        codex = routed("codex", understanding="no")
        self.assertEqual(profile(codex.stages[1]), ("gpt-6-luna", "medium"))
        claude = routed("claude-code", understanding="no")
        self.assertEqual(claude.stages[1]["model"], "claude-haiku-4-5")

    def test_risk_tier_raises_only_the_planner_and_reviewer_effort(self):
        for platform, judge in (("codex", SOL), ("claude-code", OPUS)):
            for fact, tier, effort in (
                ({"changes_security_or_payment_logic": "yes"}, "elevated", "xhigh"),
                ({"irreversible_or_ledger_or_crypto": "yes"}, "critical", "max"),
            ):
                with self.subTest(platform=platform, tier=tier):
                    result = routed(platform, **fact)
                    self.assertEqual(result.risk_tier, tier)
                    self.assertEqual(profile(result.stages[0]), (judge, effort))
                    self.assertEqual(result.pipeline["review"]["effort"], effort)
                    self.assertNotEqual(result.stages[1]["model"], judge)

    def test_the_fast_trivial_edit_and_read_only_task_types_keep_their_single_stage(self):
        # L1 is single-stage without review only through the fast path (no understanding needed + a deterministic check).
        fast = routed("codex", understanding="no", check_available=True, mechanical_only="yes")
        self.assertEqual((fast.level, fast.mode, fast.pipeline["review"]), ("L1", "single", None))
        regular = routed("codex", understanding="no", check_available=False, mechanical_only="yes")
        self.assertEqual((regular.level, regular.mode), ("L1", "two_stage"))
        self.assertIsNotNone(regular.pipeline["review"])
        for task_type in ("design", "review"):
            with self.subTest(task_type=task_type):
                result = routed("codex", task_type, files_touched="2-5")
                self.assertEqual(result.mode, "single")
                self.assertIsNone(result.pipeline)

    def test_architectural_refactoring_at_l2_stays_single_when_the_design_row_is_the_implementer(self):
        for platform, judge in (("codex", SOL), ("claude-code", OPUS)):
            with self.subTest(platform=platform):
                result = routed(platform, "architectural_refactoring", level="L2", understanding="yes")
                self.assertEqual((result.level, result.mode), ("L2", "single"))
                self.assertEqual((result.model, result.effort), (judge, "high"))
                self.assertEqual(result.stages[0]["role"], "executor")

    def test_no_two_stage_route_plans_with_the_implementer_profile(self):
        for platform in ("codex", "claude-code", "antigravity"):
            for task_type in router.CODE_CHANGE_TASK_TYPES:
                for level in ("L2", "L3", "L4", "L5"):
                    with self.subTest(platform=platform, task_type=task_type, level=level):
                        result = routed(platform, task_type, level=level)
                        if result.mode == "two_stage":
                            planner, implementer = result.stages
                            self.assertNotEqual(profile(planner), profile(implementer))


class InteractiveIsSingleStageOnlyTests(unittest.TestCase):
    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as state, mock.patch.dict(
            os.environ, {"MODEL_EFFORT_ROUTER_STATE_DIR": state}
        ), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            os.environ.pop("MODEL_EFFORT_ROUTER_SESSION", None)
            code = router.main(["x", *args])
        return code, out.getvalue(), err.getvalue()

    def test_interactive_two_stage_routes_are_refused_on_every_platform(self):
        for platform in ("codex", "claude-code", "antigravity"):
            for fmt in ("command", "json"):
                with self.subTest(platform=platform, fmt=fmt):
                    code, out, err = self.cli(
                        "--platform", platform, "--task-type", "implementation", "--level", "L3",
                        "--format", fmt, "--interactive", "--no-prompt",
                    )
                    self.assertEqual(code, 2)
                    self.assertEqual(out, "")
                    self.assertIn("single-stage only", err)
                    self.assertIn("without --interactive", err)

    def test_stage_commands_refuses_interactive_for_two_stage_results(self):
        result = routed("claude-code", level="L3")
        self.assertEqual(result.mode, "two_stage")
        with self.assertRaisesRegex(ValueError, "single-stage only"):
            router.stage_commands(result, "t", interactive=True)
        with self.assertRaisesRegex(ValueError, "single-stage only"):
            router.command_chain(result, "t", interactive=True)

    def test_interactive_single_stage_and_non_interactive_two_stage_are_unchanged(self):
        for platform in ("codex", "claude-code"):
            with self.subTest(platform=platform):
                # A pinned code change is never a fast edit (no facts), so the interactive single stage is a read-only type.
                code, out, _ = self.cli(
                    "--platform", platform, "--task-type", "review", "--level", "L1",
                    "--format", "command", "--interactive", "--no-prompt",
                )
                self.assertEqual(code, 0)
                self.assertNotIn(" exec ", out)
                self.assertNotIn(" -p ", out)
                code, out, _ = self.cli(
                    "--platform", platform, "--task-type", "implementation", "--level", "L3",
                    "--format", "command", "--no-prompt",
                )
                self.assertEqual(code, 0)
                self.assertIn("mkdir -p", out)

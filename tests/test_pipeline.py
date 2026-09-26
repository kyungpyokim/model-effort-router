import contextlib
import dataclasses
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pipeline  # noqa: E402
import router  # noqa: E402


class RolePromptTests(unittest.TestCase):
    def setUp(self):
        self.config = router.load_config(ROOT / "config" / "model-map.json")

    def test_role_prompts_are_specific_and_do_not_inflate_normal_changes(self):
        result = router.route("fix a validation typo", "codex", self.config, "L3", "implementation")
        planner, implementer = router.stage_commands(result, "fix a validation typo")

        self.assertEqual(router.SCHEMA_VERSION, 7)
        self.assertIn("PLAN\nProduce the minimum implementation plan needed for this task.", planner[-1])
        self.assertIn("IMPLEMENT\nImplement the approved plan without expanding scope.", implementer[-1])
        self.assertNotIn("architectural refactoring", planner[-1].lower())
        self.assertNotIn("architectural refactoring", implementer[-1].lower())

    def test_single_stage_design_and_review_prompts_name_their_roles(self):
        for task_type, expected in (
            ("design", "DESIGN\nProduce the architecture/design plan needed for this task."),
            ("review", "REVIEW\nReview the implementation against the requirements and plan."),
        ):
            with self.subTest(task_type=task_type):
                result = router.route("inspect the router", "codex", self.config, "L2", task_type)
                command = router.stage_commands(result, "inspect the router")[0]
                self.assertIn(expected, command[-1])

    def test_runtime_reviewer_prompt_names_the_review_role(self):
        self.assertIn(
            "REVIEW\nReview the implementation against the requirements and plan.",
            pipeline.REVIEW_INSTRUCTIONS,
        )


FAKE_CODEX = """#!{python}
import json, os, pathlib, sys
argv = sys.argv[1:]
text = " ".join(argv)
role = next((name for marker, name in (
    ("merged verification", "review"), ("fix stage", "fix"),
    ("planning stage", "plan"),
) if marker in text), "execute")
directory = pathlib.Path(os.environ["FAKE_DIR"])
index = int((directory / "count").read_text()) if (directory / "count").exists() else 0
(directory / "count").write_text(str(index + 1))
with (directory / "calls.jsonl").open("a") as stream:
    stream.write(json.dumps({{"role": role, "model": argv[argv.index("-m") + 1], "effort": [a for a in argv if a.startswith("model_reasoning_effort=")], "text": text}}) + chr(10))
replies = json.loads((directory / "replies.json").read_text())
reply = replies[index] if index < len(replies) else {{}}
if reply.get("touch"):
    pathlib.Path(reply["touch"]).write_text("x")
if role == "plan" and not reply.get("no_plan"):
    print(json.dumps({{
        "schema_version": 1,
        "analysis": {{"current_structure": [], "constraints": [], "affected_areas": [], "risks": []}},
        "implementation_plan": {{"steps": [], "expected_files": [], "compatibility_requirements": []}},
        "validation": {{"commands": [], "acceptance_criteria": [], "rollback_notes": []}},
    }}))
else:
    print(reply.get("out", ""))
sys.exit(reply.get("rc", 0))
"""


def fast_route(platform="codex", task_type="implementation"):
    """A genuinely single-stage L1 code-change route: the trivial-edit fast path (explicit no-understanding fact + a check)."""
    config = router.load_config(ROOT / "config" / "model-map.json")
    classification = dataclasses.replace(
        router.pinned_classification(task_type, "L1"), facts=dict(router.TRIVIAL_EDIT_FACTS)
    )
    result = router.route("t", platform, config, classifier=lambda _: classification, check_available=True)
    assert (result.mode, result.fast_path) == ("single", "trivial_edit")
    return result


class PipelineCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        fake = self.dir / "codex"
        fake.write_text(FAKE_CODEX.format(python=sys.executable), encoding="utf-8")
        fake.chmod(0o755)
        self.work = self.dir / "work"
        self.work.mkdir()
        old_path, old_dir = os.environ.get("PATH"), os.environ.get("FAKE_DIR")
        os.environ["PATH"] = f"{self.dir}{os.pathsep}{old_path}"
        os.environ["FAKE_DIR"] = str(self.dir)
        self.addCleanup(os.environ.__setitem__, "PATH", old_path)
        self.addCleanup(lambda: os.environ.pop("FAKE_DIR") if old_dir is None else os.environ.__setitem__("FAKE_DIR", old_dir))

    def payload(self, level="L4", task_type="implementation", platform="codex", critical=False, fast=False):
        config = router.load_config(ROOT / "config" / "model-map.json")
        if fast:
            result = fast_route(platform, task_type)
        else:
            result = router.route("do the thing", platform, config, level, task_type, critical=critical)
        return router.result_payload(result, router.stage_commands(result, "do the thing"), "do the thing")

    def run_pipeline(self, replies, payload=None, tests=("true",)):
        (self.dir / "replies.json").write_text(json.dumps(replies), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = pipeline.run_route(payload or self.payload(), list(tests), str(self.work))
        calls = [json.loads(line) for line in (self.dir / "calls.jsonl").read_text().splitlines()] if (self.dir / "calls.jsonl").exists() else []
        return rc, calls

    def roles(self, calls):
        return [call["role"] for call in calls]

    def git_repo(self):
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        (self.work / "a.txt").write_text("a")
        for args in (["init", "-q"], ["add", "."], ["commit", "-qm", "init"]):
            subprocess.run(["git", *args], cwd=self.work, env=env, check=True, capture_output=True)


class PipelineRunTests(PipelineCase):
    # L4 code changes are two-stage now: every run starts with the judge's plan, so replies lead with a plan step.
    def test_green_run_ends_with_one_sol_review_at_high_effort(self):
        rc, calls = self.run_pipeline([{}, {}, {"out": "no findings\nVERDICT: PASS"}])
        self.assertEqual(rc, 0)
        self.assertEqual(self.roles(calls), ["plan", "execute", "review"])
        self.assertEqual((calls[0]["model"], calls[2]["model"]), ("gpt-6-sol", "gpt-6-sol"))
        self.assertIn("model_reasoning_effort=high", calls[2]["effort"])
        self.assertNotEqual(calls[1]["model"], "gpt-6-sol")

    def test_failing_test_goes_to_the_implementer_with_a_log_tail_not_to_a_judge(self):
        flag = self.work / "flag"
        rc, calls = self.run_pipeline(
            [{}, {}, {"touch": str(flag)}, {"out": "VERDICT: PASS"}], tests=[f"echo boom >&2; test -f {flag}"]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(self.roles(calls), ["plan", "execute", "fix", "review"])
        self.assertIn("(exit 1)", calls[2]["text"])
        self.assertIn("boom", calls[2]["text"])
        self.assertNotEqual(calls[2]["model"], "gpt-6-sol")
        self.assertIn("PASS: ", calls[3]["text"])

    def test_tests_that_never_pass_fix_twice_then_replan_once_then_stop(self):
        rc, calls = self.run_pipeline([{}] * 9, tests=["false"])
        self.assertEqual(rc, pipeline.EXIT_GAVE_UP)
        self.assertEqual(self.roles(calls), ["plan", "execute", "fix", "fix", "plan", "execute", "fix", "fix"])
        self.assertEqual(calls[4]["model"], "gpt-6-sol")
        self.assertNotIn("review", self.roles(calls))

    def test_review_fail_is_fixed_once_then_re_reviewed(self):
        rc, calls = self.run_pipeline([{}, {}, {"out": "null deref\nVERDICT: FAIL"}, {}, {"out": "VERDICT: PASS"}])
        self.assertEqual(rc, 0)
        self.assertEqual(self.roles(calls), ["plan", "execute", "review", "fix", "review"])
        self.assertIn("null deref", calls[3]["text"])
        self.assertNotEqual(calls[3]["model"], "gpt-6-sol")

    def test_second_review_fail_replans_with_the_planning_model(self):
        fail = {"out": "VERDICT: FAIL"}
        rc, calls = self.run_pipeline([{}, {}, fail, {}, fail, {}, {}, {"out": "VERDICT: PASS"}])
        self.assertEqual(rc, 0)
        self.assertEqual(self.roles(calls), ["plan", "execute", "review", "fix", "review", "plan", "execute", "review"])
        self.assertEqual(calls[5]["model"], "gpt-6-sol")

    def test_review_fails_are_capped(self):
        fail = {"out": "VERDICT: FAIL"}
        rc, calls = self.run_pipeline([{}, {}, fail, {}, fail, {}, {}, fail, {}, fail, {}])
        self.assertEqual(rc, pipeline.EXIT_GAVE_UP)
        # The route's own plan is not a replan: exactly one more plan step follows it.
        self.assertEqual(self.roles(calls).count("plan"), 2)
        self.assertEqual(self.roles(calls).count("review"), 4)

    def test_a_review_without_a_verdict_stops_instead_of_passing(self):
        rc, calls = self.run_pipeline([{}, {}, {"out": "looks fine to me"}])
        self.assertEqual(rc, pipeline.EXIT_NO_VERDICT)
        self.assertEqual(self.roles(calls), ["plan", "execute", "review"])

    def test_implementer_escalation_evidence_triggers_a_replan(self):
        rc, calls = self.run_pipeline([{}, {"out": "ESCALATE: public API change needed"}, {}, {}, {"out": "VERDICT: PASS"}])
        self.assertEqual(rc, 0)
        self.assertEqual(self.roles(calls), ["plan", "execute", "plan", "execute", "review"])
        self.assertIn("public API change needed", calls[2]["text"])

    def test_a_failing_stage_stops_the_run_with_its_exit_code(self):
        rc, calls = self.run_pipeline([{}, {"rc": 7}])
        self.assertEqual(rc, 7)
        self.assertEqual(self.roles(calls), ["plan", "execute"])

    def test_a_failing_plan_stops_the_run_before_the_implementer(self):
        rc, calls = self.run_pipeline([{"rc": 7}])
        self.assertEqual((rc, self.roles(calls)), (7, ["plan"]))

    def test_two_stage_route_plans_first_and_keeps_the_route_plan_dir_until_asked(self):
        payload = self.payload(level="L5")
        plan_dir = Path(payload["steps"][0]["output"]["path"]).parent
        self.addCleanup(lambda: __import__("shutil").rmtree(plan_dir, ignore_errors=True))
        rc, calls = self.run_pipeline([{}, {}, {"out": "VERDICT: PASS"}], payload=payload)
        self.assertEqual(rc, 0)
        self.assertEqual(self.roles(calls), ["plan", "execute", "review"])
        self.assertEqual(json.loads((plan_dir / "state.json").read_text())["phase"], "done")

    def test_a_fast_trivial_edit_has_no_review_and_no_replan(self):
        # Every code change gets a judge plan and review (L1 too); only the fast trivial edit keeps the bare fix loop.
        self.assertIsNotNone(self.payload(level="L2")["pipeline"]["review"])
        self.assertIsNotNone(self.payload(level="L1")["pipeline"]["review"])
        payload = self.payload(fast=True)
        self.assertEqual((payload["pipeline"]["review"], payload["pipeline"]["replan"]), (None, None))
        rc, calls = self.run_pipeline([{}] * 5, payload=payload, tests=["false"])
        self.assertEqual(rc, pipeline.EXIT_GAVE_UP)
        self.assertEqual(self.roles(calls), ["execute", "fix", "fix"])

    def test_a_route_without_a_pipeline_block_just_executes(self):
        payload = self.payload(level="L4")
        payload.pop("pipeline")
        rc, calls = self.run_pipeline([{}, {}], payload=payload)
        self.assertEqual((rc, self.roles(calls)), (0, ["plan", "execute"]))

    def test_a_single_stage_route_without_a_pipeline_block_just_executes(self):
        single = self.payload(fast=True)
        single.pop("pipeline")
        rc, calls = self.run_pipeline([{}], payload=single)
        self.assertEqual((rc, self.roles(calls)), (0, ["execute"]))

    def test_invalid_pipeline_stage_is_rejected(self):
        payload = self.payload(level="L4")
        payload["pipeline"]["review"]["effort"] = "turbo"
        with self.assertRaises(ValueError):
            pipeline.Pipeline.validate(payload)


class ReviewFailureTaxonomyTests(PipelineCase):
    """A review FAIL carries a type, and the fail loop reacts to the type (see references/routing-policy.md)."""

    FAIL = {"out": "missing case\nFAILURE: edge_case\nVERDICT: FAIL"}
    BARE = {"out": "no type reported\nVERDICT: FAIL"}

    def efforts(self, calls, role="review"):
        return [call["effort"] for call in calls if call["role"] == role]

    def test_an_untyped_fail_keeps_the_pre_taxonomy_fix_path(self):
        rc, calls = self.run_pipeline([{}, {}, self.BARE, {}, {"out": "VERDICT: PASS"}])
        self.assertEqual(rc, 0)
        self.assertEqual(self.roles(calls), ["plan", "execute", "review", "fix", "review"])
        self.assertEqual(self.efforts(calls), [["model_reasoning_effort=high"]] * 2)

    def test_an_edge_case_fail_escalates_the_review_one_rung_once(self):
        rc, calls = self.run_pipeline([{}, {}, self.FAIL, {}, {"out": "VERDICT: PASS"}])
        self.assertEqual(rc, 0)
        self.assertEqual(self.roles(calls), ["plan", "execute", "review", "fix", "review"])
        self.assertEqual(self.efforts(calls), [["model_reasoning_effort=high"], ["model_reasoning_effort=xhigh"]])

    def test_the_escalation_is_bounded_to_one_per_run(self):
        fail = self.FAIL
        rc, calls = self.run_pipeline([{}, {}, fail, {}, fail, {}, {}, {"out": "VERDICT: PASS"}])
        self.assertEqual(rc, 0)
        self.assertEqual(self.roles(calls).count("plan"), 2)  # the second edge_case re-plans
        self.assertEqual(self.efforts(calls), [
            ["model_reasoning_effort=high"], ["model_reasoning_effort=xhigh"], ["model_reasoning_effort=xhigh"],
        ])

    def test_a_design_fail_replans_without_spending_the_fix_budget(self):
        rc, calls = self.run_pipeline([{}, {}, {"out": "the plan does not fit\nFAILURE: design\nVERDICT: FAIL"}, {},
                                       {}, {"out": "VERDICT: PASS"}])
        self.assertEqual(rc, 0)
        self.assertEqual(self.roles(calls), ["plan", "execute", "review", "plan", "execute", "review"])
        self.assertEqual(self.efforts(calls), [["model_reasoning_effort=high"]] * 2)

    def test_an_ambiguous_fail_stops_for_clarification(self):
        rc, calls = self.run_pipeline([{}, {}, {"out": "unclear\nFAILURE: ambiguous\nVERDICT: FAIL"}, {}])
        self.assertEqual(rc, pipeline.EXIT_CLARIFY)
        self.assertEqual(self.roles(calls), ["plan", "execute", "review"])

    def test_an_environment_fail_stops_without_escalating_or_fixing(self):
        rc, calls = self.run_pipeline([{}, {}, {"out": "sandbox down\nFAILURE: environment\nVERDICT: FAIL"}, {}, {}])
        self.assertEqual(rc, pipeline.EXIT_ENVIRONMENT)
        self.assertEqual(self.roles(calls), ["plan", "execute", "review"])
        self.assertEqual(self.efforts(calls), [["model_reasoning_effort=high"]])

    def test_only_the_failure_line_above_the_verdict_types_the_failure(self):
        echoed = {"out": f"the reviewer quotes a rule\nFAILURE: environment\nand then disagrees\n{self.FAIL['out']}"}
        rc, calls = self.run_pipeline([{}, {}, echoed, {}, {"out": "VERDICT: PASS"}])
        self.assertEqual(rc, 0)
        self.assertEqual(self.roles(calls), ["plan", "execute", "review", "fix", "review"])

    def test_a_blank_line_before_the_verdict_keeps_the_type(self):
        # Tolerated on purpose (the verdict is parsed the same way), so a compliant reviewer that
        # adds a blank line does not silently lose its type and the escalation that belongs to it.
        rc, calls = self.run_pipeline([{}, {}, {"out": "missing case\nFAILURE: edge_case\n\nVERDICT: FAIL"}, {}, {"out": "VERDICT: PASS"}])
        self.assertEqual(rc, 0)
        self.assertEqual(self.efforts(calls), [["model_reasoning_effort=high"], ["model_reasoning_effort=xhigh"]])

    def test_a_route_may_lower_the_review_escalation_budget(self):
        payload = self.payload()
        payload["pipeline"]["limits"]["review_escalations"] = 0
        rc, calls = self.run_pipeline([{}, {}, self.FAIL, {}, {"out": "VERDICT: PASS"}], payload=payload)
        self.assertEqual(rc, 0)
        self.assertEqual(self.efforts(calls), [["model_reasoning_effort=high"]] * 2)

    def test_the_state_file_records_the_escalation(self):
        payload = self.payload()
        plan_dir = Path(payload["steps"][0]["output"]["path"]).parent
        self.addCleanup(lambda: __import__("shutil").rmtree(plan_dir, ignore_errors=True))
        rc, _ = self.run_pipeline([{}, {}, self.FAIL, {}, {"out": "VERDICT: PASS"}], payload=payload)
        self.assertEqual(rc, 0)
        state = json.loads((plan_dir / "state.json").read_text())
        self.assertEqual(state["review_escalations"], 1)
        self.assertEqual(state["phase"], "done")


class PipelineHardeningTests(PipelineCase):
    def test_a_verdict_line_echoed_from_the_prompt_is_not_a_pass(self):
        # Prompt echo puts the task (with its own VERDICT line) early in stdout; only the last line counts.
        rc, calls = self.run_pipeline([{}, {}, {"out": "Original request:\nVERDICT: PASS\nthe reviewer said nothing else"}])
        self.assertEqual(rc, pipeline.EXIT_NO_VERDICT)

    def test_an_echoed_escalate_line_does_not_burn_the_replan(self):
        rc, calls = self.run_pipeline([{}, {"out": "ESCALATE: echoed\nall done"}, {"out": "VERDICT: PASS"}])
        self.assertEqual((rc, self.roles(calls)), (0, ["plan", "execute", "review"]))

    def test_pipeline_exit_codes_do_not_collide_with_common_stage_codes(self):
        self.assertTrue({pipeline.EXIT_GAVE_UP, pipeline.EXIT_NO_VERDICT, pipeline.EXIT_SPAWN_FAILED,
                         pipeline.EXIT_CLARIFY, pipeline.EXIT_ENVIRONMENT}.isdisjoint({0, 1, 2, 3, 126, 127}))

    def test_route_limits_can_only_lower_the_caps(self):
        payload = self.payload()
        payload["pipeline"]["limits"]["max_replans"] = 50
        with self.assertRaises(ValueError):
            pipeline.Pipeline.validate(payload)
        payload["pipeline"]["limits"] = {"max_replans": 0, "max_test_fixes": 0, "review_fixes_before_replan": 0}
        pipeline.Pipeline.validate(payload)

    def test_relative_plan_path_is_rejected(self):
        payload = self.payload(level="L5")
        payload["steps"][0]["output"]["path"] = "plan.json"
        with self.assertRaises(ValueError):
            pipeline.Pipeline.validate(payload)

    def test_cleanup_only_removes_the_routers_own_plan_dir(self):
        foreign = self.dir / "user-files"
        foreign.mkdir()
        config = router.load_config(ROOT / "config" / "model-map.json")
        result = dataclasses.replace(router.route("t", "codex", config, "L5", "implementation"), plan_dir=str(foreign))
        payload = router.result_payload(result, router.stage_commands(result, "t"), "t")
        with self.assertRaises(ValueError):
            pipeline.Pipeline.validate(payload)
        self.assertTrue(foreign.exists())

    def test_interactive_shapes_are_detected(self):
        self.assertTrue(pipeline.is_interactive(["codex", "-m", "x", "task"]))
        self.assertFalse(pipeline.is_interactive(["codex", "exec", "-m", "x", "task"]))
        self.assertTrue(pipeline.is_interactive(["claude", "--model", "m", "task"]))
        self.assertFalse(pipeline.is_interactive(["claude", "-p", "--model", "m", "task"]))
        self.assertTrue(pipeline.is_interactive(["agy", "--model", "m", "--prompt-interactive", "t"]))
        self.assertFalse(pipeline.is_interactive(["agy", "--model", "m", "--prompt", "t"]))

    def test_stored_interactive_route_keeps_the_terminal(self):
        # Two-stage routes are never interactive, so the interactive replay is a fast single-stage route.
        result = fast_route("codex")
        payload = router.result_payload(result, router.stage_commands(result, "t", interactive=True), "t")
        route_file = self.dir / "route.json"
        route_file.write_text(json.dumps(payload), encoding="utf-8")
        (self.dir / "replies.json").write_text("[{}]", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = pipeline.main(["--route-file", str(route_file), "--test-cmd", "true"])
        self.assertEqual(rc, 0)
        calls = [json.loads(line) for line in (self.dir / "calls.jsonl").read_text().splitlines()]
        self.assertEqual(len(calls), 1)
        self.assertFalse((self.work / "state.json").exists())


class ReviewHistoryTests(PipelineCase):
    """The append-only per-attempt review record in state.json (frozen contract, stage policy spec).

    The reference case: cycle 0 attempt 1 runs high and FAILs with edge_case, escalating to xhigh;
    cycle 0 attempt 2 runs xhigh; a re-plan starts cycle 1 at attempt 1 with the resolved policy's
    effort. Attempt numbering is cycle-local, never the whole history's length.
    """

    EDGE_CASE_FAIL = {"out": "missing case\nFAILURE: edge_case\nVERDICT: FAIL"}
    DESIGN_FAIL = {"out": "the plan does not fit\nFAILURE: design\nVERDICT: FAIL"}

    def plan_dir(self, payload):
        directory = Path(payload["steps"][0]["output"]["path"]).parent
        self.addCleanup(lambda: __import__("shutil").rmtree(directory, ignore_errors=True))
        return directory

    def history(self, payload):
        return json.loads((self.plan_dir(payload) / "state.json").read_text())["review"]["history"]

    def test_a_fail_then_escalated_pass_keeps_both_attempts(self):
        payload = self.payload()
        rc, calls = self.run_pipeline([{}, {}, self.EDGE_CASE_FAIL, {}, {"out": "VERDICT: PASS"}], payload=payload)
        self.assertEqual(rc, 0)
        self.assertEqual(self.roles(calls), ["plan", "execute", "review", "fix", "review"])
        self.assertEqual(self.history(payload), [
            {"cycle": 0, "attempt": 1, "effort": "high", "verdict": "FAIL", "failure_type": "edge_case", "escalated": True, "effort_after": "xhigh"},
            {"cycle": 0, "attempt": 2, "effort": "xhigh", "verdict": "PASS", "failure_type": None, "escalated": False, "effort_after": None},
        ])

    def test_a_replan_starts_a_new_cycle_and_keeps_earlier_entries_unchanged(self):
        payload = self.payload()
        rc, calls = self.run_pipeline(
            [{}, {}, self.EDGE_CASE_FAIL, {}, self.EDGE_CASE_FAIL, {}, {}, self.DESIGN_FAIL], payload=payload
        )
        self.assertEqual(rc, pipeline.EXIT_GAVE_UP)
        self.assertEqual(self.roles(calls).count("plan"), 2)
        self.assertEqual(self.history(payload), [
            # Entry 1 is asserted against its literal shape after a later cycle appended: an
            # append-only record cannot rewrite the attempt that ran before the re-plan.
            {"cycle": 0, "attempt": 1, "effort": "high", "verdict": "FAIL", "failure_type": "edge_case", "escalated": True, "effort_after": "xhigh"},
            # The second attempt kept the raised rung; the escalation budget was already spent.
            {"cycle": 0, "attempt": 2, "effort": "xhigh", "verdict": "FAIL", "failure_type": "edge_case", "escalated": False, "effort_after": None},
            # Cycle-local numbering: attempt restarts at 1, and the effort raise persists for the
            # whole run (the stage was raised, the budget is run-wide).
            {"cycle": 1, "attempt": 1, "effort": "xhigh", "verdict": "FAIL", "failure_type": "design", "escalated": False, "effort_after": None},
        ])
        state = json.loads((self.plan_dir(payload) / "state.json").read_text())
        self.assertEqual(
            {key: state[key] for key in ("reviews", "replans", "review_escalations")},
            {"reviews": 3, "replans": 1, "review_escalations": 1},
        )
        # `test_fixes`/`review_fixes` are current-cycle counters (the re-plan reset them, as the
        # fix caps are per cycle); run-wide per-call counts come from the usage sink's `stage`
        # records, and the run-wide attempts are the history asserted above.
        self.assertEqual((state["test_fixes"], state["review_fixes"]), (0, 0))

    def test_a_review_without_a_verdict_is_recorded_as_null_not_as_fail(self):
        payload = self.payload()
        rc, _ = self.run_pipeline([{}, {}, {"out": "looks fine to me"}], payload=payload)
        self.assertEqual(rc, pipeline.EXIT_NO_VERDICT)
        self.assertEqual(self.history(payload), [
            {"cycle": 0, "attempt": 1, "effort": "high", "verdict": None, "failure_type": None, "escalated": False, "effort_after": None},
        ])

    def test_an_environment_fail_is_recorded_and_stops_without_escalating(self):
        payload = self.payload()
        rc, calls = self.run_pipeline([{}, {}, {"out": "sandbox down\nFAILURE: environment\nVERDICT: FAIL"}, {}], payload=payload)
        self.assertEqual(rc, pipeline.EXIT_ENVIRONMENT)
        self.assertEqual(self.roles(calls), ["plan", "execute", "review"])
        self.assertEqual(self.history(payload)[0]["failure_type"], "environment")
        self.assertFalse(self.history(payload)[0]["escalated"])

    def test_the_changed_nothing_path_records_no_attempt(self):
        # The run failed before any review call was spent, so there is no attempt to record.
        self.git_repo()
        payload = self.payload()
        rc, calls = self.run_pipeline([{}] * 9, payload=payload)
        self.assertEqual(rc, pipeline.EXIT_GAVE_UP)
        self.assertNotIn("review", self.roles(calls))
        state = json.loads((self.plan_dir(payload) / "state.json").read_text())
        self.assertEqual((state["reviews"], state["review"]["history"]), (0, []))

    def test_a_nested_review_update_preserves_other_review_keys(self):
        payload = self.payload()
        directory = self.plan_dir(payload)
        runner = pipeline.Pipeline(payload, ["true"], str(self.work), directory, directory / "plan.json")
        runner.state("implement")
        state = json.loads((directory / "state.json").read_text())
        state["review"]["future_key"] = {"kept": True}
        (directory / "state.json").write_text(json.dumps(state), encoding="utf-8")
        runner.record_review("PASS", None, effort="high")
        runner.state("done")
        written = json.loads((directory / "state.json").read_text())
        self.assertEqual(written["review"]["future_key"], {"kept": True})
        self.assertEqual(len(written["review"]["history"]), 1)

    def test_an_unreadable_state_file_is_replaced_not_fatal(self):
        payload = self.payload()
        directory = self.plan_dir(payload)
        (directory / "state.json").write_text("{not json", encoding="utf-8")
        runner = pipeline.Pipeline(payload, ["true"], str(self.work), directory, directory / "plan.json")
        runner.state("done")
        self.assertEqual(json.loads((directory / "state.json").read_text())["phase"], "done")


class PipelineFailClosedTests(PipelineCase):
    def test_an_implementer_that_changed_nothing_fails_review_without_a_reviewer_call(self):
        self.git_repo()
        rc, calls = self.run_pipeline([{}] * 9)
        self.assertEqual(rc, pipeline.EXIT_GAVE_UP)
        self.assertNotIn("review", self.roles(calls))
        self.assertEqual(self.roles(calls)[:4], ["plan", "execute", "fix", "plan"])

    def test_a_real_change_reaches_the_reviewer_with_its_diff(self):
        self.git_repo()
        rc, calls = self.run_pipeline([{}, {"touch": str(self.work / "a.txt")}, {"out": "VERDICT: PASS"}])
        self.assertEqual(rc, 0)
        self.assertEqual(self.roles(calls), ["plan", "execute", "review"])

    def test_a_planner_that_wrote_no_plan_stops_the_run(self):
        payload = self.payload(level="L5")
        plan_dir = Path(payload["steps"][0]["output"]["path"]).parent
        self.addCleanup(lambda: __import__("shutil").rmtree(plan_dir, ignore_errors=True))
        rc, calls = self.run_pipeline([{"no_plan": True}], payload=payload)
        self.assertEqual(rc, pipeline.EXIT_NO_PLAN)
        self.assertEqual(self.roles(calls), ["plan"])

    def test_stage_logs_are_phase_based_and_hide_the_command_unless_verbose(self):
        (self.dir / "replies.json").write_text(json.dumps([{}, {}, {"out": "VERDICT: PASS"}]), encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            pipeline.run_route(self.payload(), ["true"], str(self.work))
        text = err.getvalue()
        self.assertIn("phase=plan model=gpt-6-sol effort=high", text)
        self.assertIn("phase=implement model=gpt-6-luna effort=xhigh", text)
        self.assertIn("phase=review model=gpt-6-sol effort=high attempt=1", text)
        self.assertNotIn("command:", text)


class ClaudeAccessTests(unittest.TestCase):
    def commands(self, level="L5", critical=False):
        config = router.load_config(ROOT / "config" / "model-map.json")
        result = router.route("t", "claude-code", config, level, "implementation", critical=critical)
        return router.stage_commands(result, "t")

    def test_only_implement_and_fix_stages_may_edit(self):
        planner, implementer = self.commands()
        self.assertIn("acceptEdits", implementer)
        self.assertNotIn("acceptEdits", planner)
        self.assertEqual(planner[planner.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(planner[planner.index("--disallowedTools") + 1], "Edit")
        review = router.stage_command("claude-code", {"model": "claude-opus-5-5", "effort": "high"}, "i", "p", "read")
        self.assertEqual(review[review.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(review[review.index("--disallowedTools") + 1], "Edit")
        self.assertNotIn("acceptEdits", review)
        for command in (planner, implementer, review):
            self.assertEqual(command[-2], "--")
            self.assertNotIn("--dangerously-skip-permissions", command)

    def test_single_stage_judges_are_read_only_and_implementers_edit(self):
        config = router.load_config(ROOT / "config" / "model-map.json")
        for task_type, expected in (("implementation", "acceptEdits"), ("design", "dontAsk"), ("review", "dontAsk")):
            with self.subTest(task_type=task_type):
                # Only the fast trivial edit keeps implementation single-stage; other code changes are two-stage and have no shell_command.
                result = fast_route("claude-code") if task_type == "implementation" else router.route("t", "claude-code", config, "L3", task_type)
                self.assertEqual(result.mode, "single")
                command = router.shell_command(result, "t", False)
                self.assertEqual(command[command.index("--permission-mode") + 1], expected)

    def test_interactive_claude_edits_keep_its_own_permission_prompts(self):
        result = fast_route("claude-code")
        self.assertEqual(result.mode, "single")
        command = router.shell_command(result, "t", True)
        self.assertEqual(command[command.index("--permission-mode") + 1], "acceptEdits")

    def test_interactive_claude_inspect_is_read_only(self):
        config = router.load_config(ROOT / "config" / "model-map.json")
        result = router.route("t", "claude-code", config, "L1", "inspect")
        command = router.shell_command(result, "t", True)
        self.assertEqual(command[command.index("--permission-mode") + 1], "dontAsk")
        self.assertIn("Bash", command)


class RouteFileArgvGrammarTests(PipelineCase):
    def test_every_generated_route_validates(self):
        config = router.load_config(ROOT / "config" / "model-map.json")
        for platform in ("codex", "claude-code", "antigravity"):
            for level in router.LEVELS:
                for task_type in router.TASK_TYPES:
                    if task_type == "inspect" and router.LEVELS.index(level) > router.LEVELS.index(router.INSPECT_MAX_LEVEL):
                        continue
                    result = router.route("t", platform, config, level, task_type)
                    for interactive in (False, True):
                        if interactive and result.mode == "two_stage":
                            continue
                        payload = router.result_payload(result, router.stage_commands(result, "t", interactive), "t")
                        with self.subTest(platform=platform, level=level, task_type=task_type, interactive=interactive):
                            router.validated_commands(payload)

    def test_smuggled_flags_are_rejected(self):
        claude = dict(model="claude-opus-5-5", effort="high", access="edit")
        good = ["claude", "-p", "--model", "claude-opus-5-5", "--effort", "high", "--permission-mode", "acceptEdits", "--", "task"]
        router.validate_argv("claude-code", good, **claude)
        bad = (
            ("codex", ["codex", "exec", "-m", "gpt-6-sol", "-c", "sandbox_mode=danger-full-access", "task"], {}),
            ("codex", ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "-m", "gpt-6-sol", "task"], {}),
            ("codex", ["codex", "exec", "-m", "gpt-6-sol", "-c", "model_reasoning_effort=turbo", "task"], {}),
            ("codex", ["codex", "exec", "-m", "gpt-6-sol", "-c", "developer_instructions", "task"], {}),
            ("codex", ["codex", "exec", "-m", "gpt 5.6 --yolo", "task"], {}),
            ("codex", ["codex", "exec", "task"], {}),
            ("claude-code", good[:-3] + ["--dangerously-skip-permissions", "--", "task"], claude),
            ("claude-code", [*good[:-2], "--permission-mode", "bypassPermissions", "--", "task"], claude),
            ("claude-code", [*good[:-2], "--add-dir", "/", "--", "task"], claude),
            ("claude-code", ["claude", "-p", "--model", "claude-opus-5-5", "--effort", "high", "--", "task"], claude),
            ("claude-code", good, dict(claude, access="read")),
            ("claude-code", good, dict(claude, effort="max")),
            ("claude-code", good, dict(claude, model="claude-sonnet-5")),
            ("antigravity", ["agy", "--model", "Gemini 3.1 Pro (High)", "--yolo", "--prompt", "task"], {}),
            ("antigravity", ["agy", "--model", "Gemini 3.1 Pro (High)", "--prompt"], {}),
        )
        for platform, command, kwargs in bad:
            with self.subTest(command=command), self.assertRaises(ValueError):
                router.validate_argv(platform, command, **kwargs)

    def test_codex_reader_cannot_drop_its_read_only_sandbox(self):
        command = ["codex", "exec", "-m", "gpt-6-luna", "task"]
        with self.assertRaises(ValueError):
            router.validate_argv("codex", command, model="gpt-6-luna", access="read")

    def test_reader_stages_cannot_run_shell_or_write_and_the_planner_writes_only_its_plan(self):
        review = router.claude_access_flags("read")
        self.assertEqual(review[review.index("--disallowedTools") + 1:review.index("--strict-mcp-config")], ["Edit", "Write", "NotebookEdit", "Bash"])
        plan = router.claude_access_flags("plan", "/tmp/codex-route-x/plan.json")
        self.assertIn("Edit(//tmp/codex-route-x/plan.json)", plan)
        self.assertIn("Bash", plan)
        self.assertNotIn("Edit", plan[plan.index("--disallowedTools"):])
        for path in (None, "relative/plan.json", "/tmp/a (b)/plan.json"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                router.claude_access_flags("plan", path)

    def test_the_plan_rule_names_exactly_the_path_the_planner_is_told(self):
        config = router.load_config(ROOT / "config" / "model-map.json")
        result = router.route("t", "claude-code", config, "L5", "implementation")
        payload = router.result_payload(result, router.stage_commands(result, "t"), "t")
        plan_path = payload["steps"][0]["output"]["path"]
        self.assertEqual(plan_path, str(Path(plan_path).resolve()))
        self.assertNotIn(plan_path, payload["steps"][0]["command"][-1])
        self.assertIn(plan_path, payload["steps"][1]["command"][-1])

    def test_a_plan_rule_for_another_path_is_rejected(self):
        config = router.load_config(ROOT / "config" / "model-map.json")
        result = router.route("t", "claude-code", config, "L5", "implementation")
        payload = router.result_payload(result, router.stage_commands(result, "t"), "t")
        command = payload["steps"][0]["command"]
        command[command.index("--permission-mode") + 1] = "acceptEdits"
        with self.assertRaises(ValueError):
            router.validated_commands(payload)

    def test_legacy_routes_keep_the_agent_flag_but_not_permission_flags(self):
        router.validate_argv("claude-code", ["claude", "--agent", "level-3-standard", "--model", "opus", "-p", "task"], model="opus", legacy=True)
        router.validate_argv("antigravity", ["agy", "--agent", "level-3-standard", "--model", "Gemini 3.1 Pro (High)", "--prompt", "task"], legacy=True)
        with self.assertRaises(ValueError):
            router.validate_argv("claude-code", ["claude", "-p", "--model", "opus", "--permission-mode", "acceptEdits", "--", "task"], model="opus", legacy=True)
        with self.assertRaises(ValueError):
            router.validate_argv("antigravity", ["agy", "--agent", "x", "--model", "Gemini 3.1 Pro (High)", "--prompt", "task"])

    def test_replaying_a_route_with_an_injected_flag_is_refused(self):
        config = router.load_config(ROOT / "config" / "model-map.json")
        result = router.route("t", "claude-code", config, "L2", "implementation")
        payload = router.result_payload(result, router.stage_commands(result, "t"), "t")
        payload["steps"][0]["command"].insert(-2, "--dangerously-skip-permissions")
        route_file = self.dir / "route.json"
        route_file.write_text(json.dumps(payload), encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(router.main(["--route-file", str(route_file)]), 2)
            self.assertEqual(pipeline.main(["--route-file", str(route_file)]), 2)
        self.assertIn("router-generated", err.getvalue())

    def test_a_multi_stage_route_cannot_use_interactive_steps(self):
        config = router.load_config(ROOT / "config" / "model-map.json")
        result = router.route("t", "codex", config, "L5", "implementation")
        commands = router.stage_commands(result, "t")
        commands[1] = [c for c in commands[1] if c != "exec"]
        payload = router.result_payload(result, commands, "t")
        with self.assertRaises(ValueError):
            pipeline.Pipeline.validate(payload)

    def test_commits_made_by_the_implementer_still_count_as_changes(self):
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        def git(*args):
            subprocess.run(["git", *args], cwd=self.work, env=env, check=True, capture_output=True)
        (self.work / "a.txt").write_text("a")
        git("init", "-q")
        git("add", ".")
        git("commit", "-qm", "init")
        base = pipeline.git_head(str(self.work))
        self.assertEqual(pipeline.git_diff(str(self.work), base)[1], False)
        (self.work / "a.txt").write_text("changed")
        git("commit", "-qam", "implementer commit")
        diff, changed = pipeline.git_diff(str(self.work), base)
        self.assertTrue(changed)
        self.assertIn("changed", diff)


class PipelinePlanTests(unittest.TestCase):
    def payload(self, platform, level="L4", task_type="implementation", critical=False):
        config = router.load_config(ROOT / "config" / "model-map.json")
        result = router.route("t", platform, config, level, task_type, critical=critical)
        return router.result_payload(result, router.stage_commands(result, "t"), "t")

    def test_risk_tier_raises_the_review_and_replan_effort_but_not_the_implementer(self):
        for tier, effort in (("standard", "high"), ("critical", "max")):
            with self.subTest(tier=tier):
                payload = self.payload("codex", critical=tier == "critical")
                pipe = payload["pipeline"]
                self.assertEqual((pipe["review"]["effort"], pipe["replan"]["effort"]), (effort, effort))
                self.assertEqual(payload["steps"][-1]["effort"], "xhigh")
                self.assertEqual(payload["steps"][-1]["model"], "gpt-6-luna")

    def test_claude_review_is_opus_and_carries_the_agent_delegation(self):
        payload = self.payload("claude-code", critical=True)
        review = payload["pipeline"]["review"]
        self.assertEqual((review["model"], review["effort"]), ("claude-opus-5-5", "max"))
        self.assertEqual(review["agent"]["subagent_type"], "model-effort:effort-max")

    def test_two_stage_replan_reuses_the_route_planner(self):
        payload = self.payload("codex", level="L5")
        self.assertEqual(payload["pipeline"]["replan"]["model"], payload["steps"][0]["model"])

    def test_judging_task_types_have_no_pipeline(self):
        for task_type in ("design", "review"):
            self.assertIsNone(self.payload("codex", task_type=task_type)["pipeline"])

    def test_pipeline_records_the_task_but_no_execution_state(self):
        pipe = self.payload("codex")["pipeline"]
        self.assertEqual(pipe["task"], "t")
        self.assertFalse({"phase", "review_attempt", "attempt"} & set(pipe))


if __name__ == "__main__":
    unittest.main()


class TrivialEditCheckTests(PipelineCase):
    """The trivial-edit fast path has no review, so the launcher must own a deterministic check."""

    def setUp(self):
        super().setUp()
        self.git_repo()
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop(pipeline.TEST_COMMAND_ENV, None)
        self.route_file = self.dir / "route.json"

    def main(self, payload, *extra):
        self.route_file.write_text(json.dumps(payload), encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            rc = pipeline.main(["--route-file", str(self.route_file), *extra])
        return rc, err.getvalue()

    def calls(self):
        path = self.dir / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_without_a_check_the_run_is_refused_before_any_model_runs(self):
        (self.dir / "replies.json").write_text("[{}]", encoding="utf-8")
        rc, err = self.main(self.payload(fast=True))
        self.assertEqual(rc, 2)
        self.assertIn("deterministic check", err)
        self.assertEqual(self.calls(), [])

    def test_a_regular_code_change_without_a_check_is_refused_before_any_model_runs(self):
        (self.dir / "replies.json").write_text("[{}]", encoding="utf-8")
        rc, err = self.main(self.payload())
        self.assertEqual(rc, 2)
        self.assertIn("deterministic check", err)
        self.assertEqual(self.calls(), [])

    def test_a_blank_check_is_refused_before_any_model_runs(self):
        (self.dir / "replies.json").write_text("[{}]", encoding="utf-8")
        rc, err = self.main(self.payload(fast=True), "--test-cmd", "   ")
        self.assertEqual(rc, 2)
        self.assertIn("deterministic check", err)
        self.assertEqual(self.calls(), [])

    def test_an_inspect_never_runs_a_supplied_test_command(self):
        config = router.load_config(ROOT / "config" / "model-map.json")
        result = router.route("look", "codex", config, "L1", "inspect")
        payload = router.result_payload(result, router.stage_commands(result, "look"), "look")
        rc, calls = self.run_pipeline([{}], payload=payload, tests=["false"])
        self.assertEqual((rc, self.roles(calls)), (0, ["execute"]))

    def test_an_interactive_hand_off_cannot_bypass_the_check(self):
        result = fast_route("codex")
        payload = router.result_payload(result, router.stage_commands(result, "t", interactive=True), "t")
        (self.dir / "replies.json").write_text("[{}]", encoding="utf-8")
        rc, err = self.main(payload)
        self.assertEqual(rc, 2)
        self.assertIn("deterministic check", err)
        self.assertEqual(self.calls(), [])

    def test_an_interactive_regular_code_change_is_refused(self):
        config = router.load_config(ROOT / "config" / "model-map.json")
        result = router.route("t", "codex", config, "L2", "architectural_refactoring")
        payload = router.result_payload(result, router.stage_commands(result, "t", interactive=True), "t")
        rc, err = self.main(payload, "--test-cmd", "true")
        self.assertEqual(rc, 2)
        self.assertIn("trivial_edit", err)
        self.assertEqual(self.calls(), [])

    def test_the_env_check_satisfies_the_guard_and_a_green_run_only_executes(self):
        (self.dir / "replies.json").write_text("[{}]", encoding="utf-8")
        old = os.getcwd()
        os.chdir(self.work)
        self.addCleanup(os.chdir, old)
        os.environ[pipeline.TEST_COMMAND_ENV] = "true"
        rc, _ = self.main(self.payload(fast=True))
        self.assertEqual((rc, self.roles(self.calls())), (0, ["execute"]))

    def test_a_passing_check_runs_execute_only(self):
        rc, calls = self.run_pipeline([{}], payload=self.payload(fast=True), tests=["true"])
        self.assertEqual((rc, self.roles(calls)), (0, ["execute"]))

    def test_a_check_that_keeps_failing_stops_after_two_fixes_without_promotion(self):
        rc, calls = self.run_pipeline([{}] * 5, payload=self.payload(fast=True), tests=["false"])
        self.assertEqual(rc, pipeline.EXIT_GAVE_UP)
        self.assertEqual(self.roles(calls), ["execute", "fix", "fix"])


class FastPathValidationTests(PipelineCase):
    def test_absent_and_known_values_are_valid(self):
        payload = self.payload(fast=True)
        pipeline.Pipeline.validate(payload)
        payload.pop("fast_path")
        pipeline.Pipeline.validate(payload)
        inspect = router.route("look", "codex", router.load_config(ROOT / "config" / "model-map.json"), "L1", "inspect")
        pipeline.Pipeline.validate(router.result_payload(inspect, router.stage_commands(inspect, "look"), "look"))

    def test_an_unknown_fast_path_value_is_an_invalid_route(self):
        for value in ("turbo", "", 1, True, ["trivial_edit"]):
            payload = self.payload(fast=True)
            payload["fast_path"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                pipeline.Pipeline.validate(payload)

    def test_a_trivial_edit_claim_with_a_plan_stage_is_inconsistent(self):
        payload = self.payload(level="L4")
        payload["fast_path"] = "trivial_edit"
        with self.assertRaises(ValueError):
            pipeline.Pipeline.validate(payload)

    def test_replayed_trivial_edit_rechecks_its_facts(self):
        payload = self.payload(fast=True)
        payload["facts"]["changes_trust_boundary"] = "yes"
        with self.assertRaises(ValueError):
            router.validated_commands(payload)

    def test_a_trivial_edit_claim_carrying_a_review_or_replan_is_inconsistent(self):
        for key in ("review", "replan"):
            payload = self.payload(fast=True)
            payload["pipeline"][key] = self.payload(level="L4")["pipeline"][key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                pipeline.Pipeline.validate(payload)

    def test_main_reports_an_invalid_fast_path_as_an_invalid_route(self):
        payload = self.payload(fast=True)
        payload["fast_path"] = "turbo"
        route_file = self.dir / "route.json"
        route_file.write_text(json.dumps(payload), encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            rc = pipeline.main(["--route-file", str(route_file), "--test-cmd", "true"])
        self.assertEqual(rc, 2)
        self.assertIn("invalid route file", err.getvalue())

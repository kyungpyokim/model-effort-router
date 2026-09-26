"""The ambiguity gate: the request text may annotate a plan or ask the user to restate, and it
must never change the route's level, risk tier, model, effort, or stages."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import commands  # noqa: E402
import route_reuse  # noqa: E402
import router  # noqa: E402
import rules  # noqa: E402

CONFIG = router.load_config(ROOT / "config" / "model-map.json")


def classification(task_type="implementation", level="L3", **overrides):
    values = dict(
        task_type=task_type, level=level, risk_flags={flag: False for flag in router.RISK_FLAGS},
        reason="classified", source="primary", facts={"files_touched": "1"}, matched_rules=("rule",),
    )
    values.update(overrides)
    return router.Classification(**values)


class GateTableTests(unittest.TestCase):
    CASES = (
        # A named operation and a concrete target: nothing to clarify.
        ("fix the parser bug in parser.py", "implementation", "clear"),
        ("add a retry_policy helper to the client", "implementation", "clear"),
        ("OrderService must not charge twice", "implementation", "partial"),
        ("fix OrderService.refund so it does not charge twice", "implementation", "clear"),
        ("rename the field in api/models.py", "local_refactoring", "clear"),
        # One of the two is named: the planner must state its assumptions about the other.
        ("fix the login problem", "implementation", "partial"),
        ("harden the token refresh", "implementation", "partial"),
        ("payment.py", "implementation", "partial"),
        ("do the thing", "implementation", "partial"),
        # Gerunds of e-final verbs name an operation just as their imperative form does.
        ("investigating why the parser drops empty rows", "implementation", "partial"),
        ("migrating the account table", "implementation", "partial"),
        # Neither is named: nothing to assume from, so the user is asked to restate.
        ("t", "implementation", "ambiguous"),
        ("the thing", "implementation", "ambiguous"),
        ("지금 이거 좀", "implementation", "ambiguous"),
        ("", "implementation", "ambiguous"),
        # Read-only work is never gated on text shape.
        ("inspect the deployment status", "inspect", "clear"),
        ("review the retry logic", "review", "clear"),
        ("design the new migration flow", "design", "clear"),
        ("t", "inspect", "clear"),
    )

    def test_the_gate_reads_the_request_text(self):
        for task, task_type, expected in self.CASES:
            with self.subTest(task=task, task_type=task_type):
                self.assertEqual(rules.derive_ambiguity_gate(task, task_type)[0], expected)

    def test_a_settled_request_is_already_clarified(self):
        for task in ("t", "the thing", "지금 이거 좀"):
            with self.subTest(task=task):
                self.assertEqual(rules.derive_ambiguity_gate(task, "implementation", settled=True), ("clear", ""))

    def test_an_ambiguous_gate_carries_a_reason(self):
        gate, reason = rules.derive_ambiguity_gate("t", "implementation")
        self.assertEqual(gate, "ambiguous")
        self.assertIn("neither an operation nor a concrete target", reason)

    def test_gerund_alternatives_are_word_bounded(self):
        self.assertTrue(rules.AMBIGUITY_ACTION_RE.search("migrating the account table"))
        self.assertTrue(rules.AMBIGUITY_ACTION_RE.search("investigating the failure"))
        # "immigrating" ends in "migrating" but names no operation of this work.
        self.assertIsNone(rules.AMBIGUITY_ACTION_RE.search("immigrating"))


class GateIsNotDifficultyTests(unittest.TestCase):
    TASKS = ("fix the parser bug in parser.py", "fix the login problem", "t")

    def route(self, task):
        return router.route(task, "codex", CONFIG, classifier=lambda _: classification())

    def test_the_gate_never_changes_level_tier_or_stages(self):
        results = [self.route(task) for task in self.TASKS]
        self.assertEqual([result.ambiguity for result in results], ["clear", "partial", "ambiguous"])
        for result in results[1:]:
            with self.subTest(result=result.ambiguity):
                for field in ("base_level", "level", "risk_tier", "mode", "fast_path", "model", "effort"):
                    self.assertEqual(getattr(result, field), getattr(results[0], field), field)
                self.assertEqual(result.stages, results[0].stages)

    def test_a_requirement_can_be_annotated_but_never_escalates(self):
        clear, partial, ambiguous = (self.route(task) for task in self.TASKS)
        self.assertEqual((partial.level, partial.risk_tier), (clear.level, clear.risk_tier))
        self.assertEqual((ambiguous.level, ambiguous.risk_tier), (clear.level, clear.risk_tier))
        self.assertEqual(rules.EFFORT_ORDER.index(clear.stages[-1]["effort"]), rules.EFFORT_ORDER.index(partial.stages[-1]["effort"]))


class PlannerAssumptionContractTests(unittest.TestCase):
    def payload(self, task):
        result = router.route(task, "codex", CONFIG, classifier=lambda _: classification())
        self.assertEqual(result.mode, "two_stage")
        commands_for = router.stage_commands(result, task)
        return result, json.loads(json.dumps(router.result_payload(result, commands_for, task)))

    def test_a_partial_request_pins_the_assumptions_clause(self):
        result, payload = self.payload("payment.py")
        self.assertEqual((payload["ambiguity"], result.ambiguity), ("partial", "partial"))
        instructions, _, _ = router.expected_stage_text(payload, 0, payload["steps"][0]["output"]["path"])
        self.assertIn(commands.PLANNER_UNDERSPECIFIED_CLAUSE, instructions)
        router.validated_commands(payload)  # the pinned text and the payload agree, so it replays

    def test_a_clear_request_carries_no_clause(self):
        _, payload = self.payload("fix the parser bug in parser.py")
        self.assertEqual(payload["ambiguity"], "clear")
        instructions, _, _ = router.expected_stage_text(payload, 0, payload["steps"][0]["output"]["path"])
        self.assertNotIn(commands.PLANNER_UNDERSPECIFIED_CLAUSE, instructions)
        router.validated_commands(payload)

    def test_the_clause_is_part_of_the_route_contract(self):
        # A payload that drops its own ambiguity no longer matches the command built for it, so the
        # route is refused as tampered rather than silently replayed with the wrong planner prompt.
        _, payload = self.payload("payment.py")
        payload["ambiguity"] = "clear"
        with self.assertRaisesRegex(ValueError, "does not carry the generated instructions"):
            router.validated_commands(payload)


class AmbiguityCliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name) / "state"
        self.workspace = Path(self._tmp.name) / "ws"
        self.workspace.mkdir()
        env = mock.patch.dict(os.environ, {route_reuse.STATE_DIR_ENV: str(self.state)})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(os_chdir, str(Path.cwd()))
        os_chdir(str(self.workspace))

    def run_cli(self, task, *extra, classified=None):
        self.calls = []

        def fake(*_args, **_kwargs):
            self.calls.append(1)
            return classified or classification()

        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(router, "classify_task", fake), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = router.main([task, "--platform", "codex", *extra])
        return rc, out.getvalue(), err.getvalue()

    def test_an_ambiguous_request_asks_for_a_restatement_and_returns_needs_answer(self):
        rc, out, err = self.run_cli("t", "--format", "json")
        self.assertEqual(rc, router.EXIT_NEEDS_ANSWER)
        self.assertIn("Restate it with what to change and where", err)
        payload = json.loads(out)
        self.assertEqual(payload["ambiguity"], "ambiguous")
        self.assertTrue(payload["ambiguity_reason"])

    def test_the_text_route_reports_the_gate(self):
        rc, out, _ = self.run_cli("t")
        self.assertEqual(rc, router.EXIT_NEEDS_ANSWER)
        self.assertIn("ambiguity: ambiguous", out)

    def test_a_clear_request_routes_normally(self):
        rc, out, _ = self.run_cli("fix the parser bug in parser.py", "--format", "json")
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["ambiguity"], "clear")

    def test_a_partial_request_routes_normally(self):
        rc, out, _ = self.run_cli("fix the login problem", "--format", "json")
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["ambiguity"], "partial")

    def test_a_pinned_request_is_never_asked_to_restate(self):
        rc, out, _ = self.run_cli("t", "--format", "json", "--level", "L3", "--task-type", "implementation")
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["ambiguity"], "clear")

    def test_a_manual_classification_is_never_asked_to_restate(self):
        manual = classification(source="manual")
        rc, out, _ = self.run_cli("t", "--format", "json", classified=manual)
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["ambiguity"], "clear")

    def test_a_fallback_route_keeps_its_preflight_failure_exit_code(self):
        # The payload reports the truth about the request text; the fallback's own exit code and
        # guidance stay, so the gate never turns a preflight failure into a restatement request.
        rc, out, err = self.run_cli("t", "--format", "json", classified=router.fallback_classification("boom"))
        self.assertEqual(rc, 1)
        self.assertNotIn("Restate it", err)
        self.assertEqual(json.loads(out)["ambiguity"], "ambiguous")

    def test_an_ambiguous_route_is_never_stored_for_reuse(self):
        # Regression: a stored ambiguous route would come back as a reused (settled) route and run.
        first_rc, _, _ = self.run_cli("t", "--format", "json", "--session", "s1")
        second_rc, out, err = self.run_cli("t", "--format", "json", "--session", "s1")
        self.assertEqual((first_rc, second_rc), (router.EXIT_NEEDS_ANSWER, router.EXIT_NEEDS_ANSWER))
        self.assertIn("Restate it", err)
        self.assertEqual(json.loads(out)["ambiguity"], "ambiguous")
        self.assertFalse(json.loads(out)["reuse"]["reused"])
        self.assertEqual(len(self.calls), 1)

    def test_a_pre_marker_session_record_cannot_settle_a_vague_task(self):
        # Regression: a record written before the ambiguity marker existed has no marker. It is
        # still reusable, but it must not settle the gate: the route stays unanswered, so nothing
        # runs and no classifier call is spent re-deriving the same reuse.
        route_reuse.save_record("s1", str(self.workspace), {
            "task_type": "implementation", "level": "L3", "risk_tier": "standard",
            "risk_flags": {flag: False for flag in router.RISK_FLAGS},
            "facts": {"files_touched": "1"}, "matched_rules": [], "unresolved": [],
            "evidence": [], "delegability": 0, "origin": "primary",
        })
        rc, out, err = self.run_cli("t", "--format", "json", "--session", "s1")
        self.assertEqual(rc, router.EXIT_NEEDS_ANSWER)
        self.assertIn("Restate it", err)
        payload = json.loads(out)
        self.assertTrue(payload["reuse"]["reused"])
        self.assertEqual(payload["ambiguity"], "ambiguous")
        self.assertEqual(len(self.calls), 0)

    def test_a_marked_session_record_settles_a_terse_follow_up(self):
        # The marker path itself: a route stored by this version settles a follow-up that would
        # otherwise be ambiguous on its own text, and no classifier call is spent.
        first_rc, _, _ = self.run_cli("fix the parser bug in parser.py", "--format", "json", "--session", "s1")
        second_rc, out, _ = self.run_cli("also the next file", "--format", "json", "--session", "s1")
        self.assertEqual((first_rc, second_rc), (0, 0))
        payload = json.loads(out)
        self.assertTrue(payload["reuse"]["reused"])
        self.assertEqual(payload["ambiguity"], "clear")
        self.assertEqual(len(self.calls), 0)


def os_chdir(path):
    import os
    os.chdir(path)


if __name__ == "__main__":
    unittest.main()

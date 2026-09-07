from pathlib import Path
from unittest import mock
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("router", ROOT / "scripts" / "router.py")
router = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = router
SPEC.loader.exec_module(router)
CONFIG = router.load_config(ROOT / "config" / "model-map.json")

NO_FLAGS = {flag: False for flag in router.RISK_FLAGS}
BASE_FACTORS = {"scope": 1, "ambiguity": 0, "diagnosis": 0, "design": 1, "risk": 0, "verification": 1}


def classifier_output(task_type="implementation", level="L2", factors=None, flags=None, confidence=0.9, reason="Clear scoped change.", context_required=False, delegability=0, raw=True):
    payload = {
        "task_type": task_type,
        "level": level,
        "factors": dict(factors or BASE_FACTORS),
        "risk_flags": {**NO_FLAGS, **(flags or {})},
        "confidence": confidence,
        "context_required": context_required,
        "delegability": delegability,
        "reason": reason,
    }
    return json.dumps(payload) if raw else payload


def classification(task_type="implementation", level="L2", factors=None, flags=None, confidence=0.9, source="terra", delegability=0):
    return router.Classification(
        task_type=task_type,
        level=level,
        factors=dict(factors or BASE_FACTORS),
        risk_flags={**NO_FLAGS, **(flags or {})},
        confidence=confidence,
        reason="classified",
        source=source,
        context_required=False,
        delegability=delegability,
    )


def routed(task="task", platform="codex", explicit_level=None, explicit_task_type=None,
           explicit_factors=None, available_models=None, classifier=None, repo_aware=False, critical=False):
    return router.route(
        task, platform, CONFIG,
        explicit_factors=explicit_factors,
        explicit_level=explicit_level,
        explicit_task_type=explicit_task_type,
        available_models=available_models,
        classifier=classifier or (lambda _: classification()),
        repo_aware=repo_aware,
        critical=critical,
    )


class PlatformClassifierTests(unittest.TestCase):
    def test_codex_output_schema_requires_every_top_level_property(self):
        self.assertEqual(
            set(router.CLASSIFIER_SCHEMA["required"]),
            set(router.CLASSIFIER_SCHEMA["properties"]),
        )

    def test_uses_fixed_low_effort_terra_with_v2_schema(self):
        completed = subprocess.CompletedProcess([], 0, classifier_output(), "")
        captured = {}

        def run_classifier(command, **kwargs):
            captured["schema"] = json.loads(Path(command[command.index("--output-schema") + 1]).read_text(encoding="utf-8"))
            return completed

        with mock.patch.object(router.subprocess, "run", side_effect=run_classifier) as run:
            result = router.classify_task("add a settings page", timeout=7)
        command = run.call_args.args[0]
        self.assertEqual(command[0:2], ["codex", "exec"])
        self.assertIn("--ephemeral", command)
        self.assertEqual(command[command.index("--model") + 1], "gpt-5.6-luna")
        self.assertIn('model_reasoning_effort="medium"', command)
        self.assertEqual(captured["schema"]["properties"]["task_type"]["enum"], list(router.TASK_TYPES))
        self.assertEqual(captured["schema"]["properties"]["risk_flags"]["required"], list(router.RISK_FLAGS))
        self.assertNotIn("hard_floor", captured["schema"]["properties"])
        self.assertEqual(result.source, "gpt-5.6-luna")
        self.assertEqual(run.call_args.kwargs["timeout"], 7)

    def test_cascading_fallback_to_terra_on_low_confidence(self):
        primary_output = classifier_output(level="L3", confidence=0.50)
        fallback_output = classifier_output(level="L4", confidence=0.85)
        calls = []

        def fake_run(command, **kwargs):
            model = command[command.index("--model") + 1]
            calls.append(model)
            out = fallback_output if model == "gpt-5.6-terra" else primary_output
            return subprocess.CompletedProcess([], 0, out, "")

        with mock.patch.object(router.subprocess, "run", side_effect=fake_run):
            result = router.classify_task("complex ambiguous task")
        self.assertEqual(calls, ["gpt-5.6-luna", "gpt-5.6-terra"])
        self.assertEqual(result.source, "gpt-5.6-terra")
        self.assertEqual(result.level, "L4")

    def test_repo_aware_uses_fallback_classifier_directly(self):
        calls = []

        def fake_run(command, **kwargs):
            model = command[command.index("--model") + 1]
            calls.append(model)
            return subprocess.CompletedProcess([], 0, classifier_output(level="L4"), "")

        with mock.patch.object(router.subprocess, "run", side_effect=fake_run):
            result = router.classify_task("fix intermittent bug", repo_aware=True)
        self.assertEqual(calls, ["gpt-5.6-terra"])
        self.assertEqual(result.source, "gpt-5.6-terra")

    def test_claude_uses_native_structured_output_without_tools_or_session(self):
        completed = subprocess.CompletedProcess([], 0, json.dumps({"structured_output": json.loads(classifier_output())}), "")
        with mock.patch.object(router.subprocess, "run", return_value=completed) as run:
            result = router.classify_task("add a settings page", platform="claude-code", timeout=7)
        command = run.call_args.args[0]
        self.assertEqual(command[:2], ["claude", "-p"])
        self.assertEqual(command[command.index("--model") + 1], "claude-haiku-4-5")
        self.assertNotIn("--effort", command)
        self.assertEqual(json.loads(command[command.index("--json-schema") + 1]), router.CLASSIFIER_SCHEMA)
        self.assertEqual(result.source, "claude-haiku-4-5")
        self.assertTrue(Path(run.call_args.kwargs["cwd"]).name.startswith("model-effort-router-"))

    def test_antigravity_uses_isolated_structured_json_classifier(self):
        completed = subprocess.CompletedProcess([], 0, json.dumps({"structured_output": json.loads(classifier_output())}), "")
        with mock.patch.object(router.subprocess, "run", return_value=completed) as run:
            result = router.classify_task("task", platform="antigravity", timeout=7)
        command = run.call_args.args[0]
        self.assertEqual(command[:2], ["agy", "--model"])
        self.assertLess(command.index("--model"), command.index("--print"))
        self.assertEqual(command.index("--print"), len(command) - 2)
        self.assertEqual(command[command.index("--model") + 1], "Gemini 3.8 Flash (Medium)")
        self.assertEqual(json.loads(command[command.index("--json-schema") + 1]), router.CLASSIFIER_SCHEMA)
        self.assertEqual(result.source, "Gemini 3.8 Flash (Medium)")

    def test_claude_cascading_fallback_uses_sonnet_medium(self):
        primary_output = json.dumps({"structured_output": json.loads(classifier_output(level="L2", confidence=0.45))})
        fallback_output = json.dumps({"structured_output": json.loads(classifier_output(level="L3", confidence=0.88))})
        calls = []

        def fake_run(command, **kwargs):
            model = command[command.index("--model") + 1]
            effort = command[command.index("--effort") + 1] if "--effort" in command else None
            calls.append((model, effort))
            out = fallback_output if model == "claude-sonnet-5" else primary_output
            return subprocess.CompletedProcess([], 0, out, "")

        with mock.patch.object(router.subprocess, "run", side_effect=fake_run):
            result = router.classify_task("ambiguous task", platform="claude-code")
        self.assertEqual(calls, [("claude-haiku-4-5", None), ("claude-sonnet-5", "medium")])
        self.assertEqual(result.source, "claude-sonnet-5")
        self.assertEqual(result.level, "L3")

    def test_antigravity_cascading_fallback_to_pro_high(self):
        primary_output = json.dumps({"structured_output": json.loads(classifier_output(level="L3", confidence=0.55))})
        fallback_output = json.dumps({"structured_output": json.loads(classifier_output(level="L5", confidence=0.90))})
        calls = []

        def fake_run(command, **kwargs):
            model = command[command.index("--model") + 1]
            calls.append(model)
            out = fallback_output if "Pro" in model else primary_output
            return subprocess.CompletedProcess([], 0, out, "")

        with mock.patch.object(router.subprocess, "run", side_effect=fake_run):
            result = router.classify_task("complex task", platform="antigravity")
        self.assertEqual(calls, ["Gemini 3.8 Flash (Medium)", "Gemini 3.1 Pro (High)"])
        self.assertEqual(result.source, "Gemini 3.1 Pro (High)")
        self.assertEqual(result.level, "L5")

    def test_timeout_process_failure_and_invalid_output_fall_back(self):
        for outcome in (
            subprocess.TimeoutExpired("codex", 1),
            OSError("missing executable"),
            subprocess.CompletedProcess([], 1, "", "failed"),
            subprocess.CompletedProcess([], 0, '{"level":"L2"}', ""),
        ):
            with self.subTest(outcome=type(outcome).__name__):
                with mock.patch.object(router.subprocess, "run", side_effect=outcome if isinstance(outcome, Exception) else None, return_value=None if isinstance(outcome, Exception) else outcome):
                    result = router.classify_task("task")
                self.assertEqual(result.task_type, router.FALLBACK_TASK_TYPE)
                self.assertEqual(result.level, "L3")
                self.assertEqual(result.source, "fallback")
                self.assertEqual(result.factors, {factor: 1 for factor in router.FACTORS})
                self.assertEqual(result.risk_flags, NO_FLAGS)

    def test_schema_validation_rejects_bad_values(self):
        valid = classifier_output(raw=False)
        for mutation in (
            lambda p: p.pop("task_type"),
            lambda p: p.update(extra=True),
            lambda p: p.update(task_type="refactoring"),
            lambda p: p.update(level="L9"),
            lambda p: p.update(factors={"scope": 1}),
            lambda p: p.update(risk_flags={**NO_FLAGS, "payment": "yes"}),
            lambda p: p.update(risk_flags={flag: False for flag in router.RISK_FLAGS[:-1]}),
            lambda p: p.update(confidence=1.5),
            lambda p: p.update(confidence=True),
            lambda p: p.update(delegability=3),
            lambda p: p.update(reason=""),
        ):
            payload = json.loads(json.dumps(valid))
            mutation(payload)
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError):
                    router.validate_classifier_output(payload)
        self.assertEqual(router.validate_classifier_output(valid).task_type, "implementation")

    def test_classifier_preserves_delegability_outside_difficulty_factors(self):
        result = router.validate_classifier_output(classifier_output(delegability=2, raw=False))
        self.assertEqual(result.delegability, 2)
        self.assertEqual(result.factors, BASE_FACTORS)

    def test_timeouts_must_be_finite_and_positive(self):
        for option in ("--classifier-timeout", "--detect-timeout"):
            for value in ("0", "-1", "nan", "inf"):
                with self.subTest(option=option, value=value), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        router.parse_args(["--platform", "codex", option, value, "task"])


class EscalationTests(unittest.TestCase):
    def test_security_flags_force_an_l4_floor(self):
        cases = (
            ("L1", {"authentication": True}, "L6"),
            ("L2", {"payment": True}, "L6"),
            ("L3", {"authorization": True}, "L6"),
            ("L1", {"security_sensitive": True}, "L6"),
            ("L6", {"security_sensitive": True}, "L6"),
            ("L7", {"security_sensitive": True}, "L7"),
        )
        for base, flags, expected in cases:
            with self.subTest(base=base, flags=flags):
                self.assertEqual(router.apply_risk_escalation(base, {**NO_FLAGS, **flags}), expected)

    def test_non_security_flags_escalate_one_level_each(self):
        self.assertEqual(router.apply_risk_escalation("L3", {**NO_FLAGS, "data_migration": True}), "L4")
        self.assertEqual(router.apply_risk_escalation("L3", {**NO_FLAGS, "public_api_change": True}), "L4")
        self.assertEqual(
            router.apply_risk_escalation("L3", {**NO_FLAGS, "data_migration": True, "public_api_change": True}),
            "L5",
        )
        self.assertEqual(router.apply_risk_escalation("L7", {**NO_FLAGS, "data_migration": True}), "L7")

    def test_no_flags_keeps_the_base_level(self):
        self.assertEqual(router.apply_risk_escalation("L2", NO_FLAGS), "L2")


class MatrixTests(unittest.TestCase):
    CODEX_IMPL = (
        ("gpt-5.6-luna", "low"),
        ("gpt-5.6-luna", "medium"),
        ("gpt-5.6-terra", "medium"),
        ("gpt-5.6-terra", "high"),
        ("gpt-5.6-sol", "high"),
        ("gpt-5.6-sol", "xhigh"),
        ("gpt-6-astra", "xhigh"),
    )
    EXPECTED_SINGLE = {
        "codex": {
            **{("implementation", level): cell for level, cell in zip(router.LEVELS, CODEX_IMPL)},
            **{("local_refactoring", level): cell for level, cell in zip(router.LEVELS, CODEX_IMPL)},
            **{(kind, level): cell for kind in ("design", "review") for level, cell in zip(router.LEVELS, (
                ("gpt-5.6-luna", "medium"),
                ("gpt-5.6-sol", "low"),
                ("gpt-5.6-sol", "medium"),
                ("gpt-5.6-sol", "high"),
                ("gpt-5.6-sol", "high"),
                ("gpt-5.6-sol", "xhigh"),
                ("gpt-6-astra", "xhigh"),
            ))},
            ("architectural_refactoring", "L1"): ("gpt-5.6-luna", "medium"),
            ("architectural_refactoring", "L2"): ("gpt-5.6-sol", "medium"),
        },
        "claude-code": {
            **{("implementation", level): cell for level, cell in zip(router.LEVELS, (
                ("claude-haiku-4-5", None), ("claude-haiku-4-5", None), ("claude-sonnet-5", "medium"), ("claude-sonnet-5", "high"),
                ("claude-fable-5-1", "medium"), ("claude-fable-5-1", "high"), ("claude-fable-5-1", "xhigh"),
            ))},
            **{("local_refactoring", level): cell for level, cell in zip(router.LEVELS, (
                ("claude-haiku-4-5", None), ("claude-haiku-4-5", None), ("claude-sonnet-5", "medium"), ("claude-sonnet-5", "high"),
                ("claude-fable-5-1", "medium"), ("claude-fable-5-1", "high"), ("claude-fable-5-1", "xhigh"),
            ))},
            **{(kind, level): cell for kind in ("design", "review") for level, cell in zip(router.LEVELS, (
                ("claude-haiku-4-5", None), ("claude-opus-5", "low"), ("claude-opus-5", "medium"), ("claude-opus-5", "high"),
                ("claude-fable-5-1", "high"), ("claude-fable-5-1", "xhigh"), ("claude-fable-5-1", "xhigh"),
            ))},
            ("architectural_refactoring", "L1"): ("claude-haiku-4-5", None),
            ("architectural_refactoring", "L2"): ("claude-opus-5", "medium"),
        },
        "antigravity": {
            **{(kind, level): cell for kind in ("implementation", "local_refactoring") for level, cell in zip(router.LEVELS, (
                ("Gemini 3.8 Flash (High)", None), ("Gemini 3.8 Flash (High)", None), ("Gemini 3.8 Flash (High)", None),
                ("Claude Sonnet 4.6 (Thinking)", None), ("Gemini 3.1 Pro (High)", None),
                ("Claude Opus 4.6 (Thinking)", None), ("Claude Opus 4.6 (Thinking)", None),
            ))},
            **{(kind, level): cell for kind in ("design", "review") for level, cell in zip(router.LEVELS, (
                ("Gemini 3.8 Flash (High)", None), ("Gemini 3.8 Flash (High)", None), ("Gemini 3.1 Pro (High)", None),
                ("Gemini 3.1 Pro (High)", None), ("Gemini 3.1 Pro (High)", None),
                ("Claude Opus 4.6 (Thinking)", None), ("Claude Opus 4.6 (Thinking)", None),
            ))},
            ("architectural_refactoring", "L1"): ("Gemini 3.8 Flash (High)", None),
            ("architectural_refactoring", "L2"): ("Gemini 3.8 Flash (High)", None),
        },
    }
    EXPECTED_STAGES = {
        "codex": {
            ("architectural_refactoring", "L3"): [("planner", "gpt-5.6-sol", "high"), ("implementer", "gpt-5.6-terra", "medium")],
            ("architectural_refactoring", "L4"): [("planner", "gpt-5.6-sol", "xhigh"), ("implementer", "gpt-5.6-terra", "high")],
            ("architectural_refactoring", "L5"): [("planner", "gpt-5.6-sol", "xhigh"), ("implementer", "gpt-5.6-terra", "high")],
            ("architectural_refactoring", "L6"): [("planner", "gpt-5.6-sol", "xhigh"), ("implementer", "gpt-5.6-sol", "xhigh")],
            ("architectural_refactoring", "L7"): [("planner", "gpt-6-astra", "xhigh"), ("implementer", "gpt-5.6-sol", "xhigh")],
        },
        "claude-code": {
            ("architectural_refactoring", "L3"): [("planner", "claude-fable-5-1", "high"), ("implementer", "claude-sonnet-5", "medium")],
            ("architectural_refactoring", "L4"): [("planner", "claude-fable-5-1", "xhigh"), ("implementer", "claude-sonnet-5", "high")],
            ("architectural_refactoring", "L5"): [("planner", "claude-fable-5-1", "xhigh"), ("implementer", "claude-sonnet-5", "high")],
            ("architectural_refactoring", "L6"): [("planner", "claude-fable-5-1", "xhigh"), ("implementer", "claude-fable-5-1", "high")],
            ("architectural_refactoring", "L7"): [("planner", "claude-fable-5-1", "max"), ("implementer", "claude-fable-5-1", "xhigh")],
        },
        "antigravity": {
            ("architectural_refactoring", "L3"): [("planner", "Gemini 3.1 Pro (High)", None), ("implementer", "Gemini 3.8 Flash (High)", None)],
            ("architectural_refactoring", "L4"): [("planner", "Gemini 3.1 Pro (High)", None), ("implementer", "Claude Sonnet 4.6 (Thinking)", None)],
            ("architectural_refactoring", "L5"): [("planner", "Gemini 3.1 Pro (High)", None), ("implementer", "Claude Sonnet 4.6 (Thinking)", None)],
            ("architectural_refactoring", "L6"): [("planner", "Claude Opus 4.6 (Thinking)", None), ("implementer", "Claude Opus 4.6 (Thinking)", None)],
            ("architectural_refactoring", "L7"): [("planner", "Claude Opus 4.6 (Thinking)", None), ("implementer", "Claude Opus 4.6 (Thinking)", None)],
        },
    }

    def test_every_matrix_cell_matches_the_final_spec(self):
        for platform in ("codex", "claude-code", "antigravity"):
            for task_type in router.TASK_TYPES:
                for level in router.LEVELS:
                    with self.subTest(cell=f"{platform}/{task_type}/{level}"):
                        result = routed(platform=platform, classifier=lambda _, t=task_type, l=level: classification(t, l))
                        self.assertEqual(result.task_type, task_type)
                        self.assertEqual(result.level, level)
                        if (task_type, level) in self.EXPECTED_SINGLE[platform]:
                            model, effort = self.EXPECTED_SINGLE[platform][(task_type, level)]
                            self.assertEqual(result.mode, "single")
                            self.assertEqual((result.model, result.effort), (model, effort))
                            self.assertIsNone(result.plan_dir)
                        else:
                            expected = self.EXPECTED_STAGES[platform][(task_type, level)]
                            self.assertEqual(result.mode, "two_stage")
                            self.assertIsNone(result.model)
                            self.assertIsNotNone(result.plan_dir)
                            self.assertEqual([(s["role"], s["model"], s["effort"]) for s in result.stages], expected)

    def test_antigravity_patterns_match_account_models_before_fallback(self):
        result = routed(
            platform="antigravity",
            classifier=lambda _: classification("implementation", "L4"),
            available_models=["Gemini 3.8 Flash (High)", "Claude Sonnet 4.6 (Thinking)"],
        )
        self.assertEqual((result.model, result.effort), ("Claude Sonnet 4.6 (Thinking)", None))


class RoutingTests(unittest.TestCase):
    def test_single_l5_to_l7_codex_routes_record_safe_orchestration_eligibility(self):
        for level in ("L5", "L6", "L7"):
            with self.subTest(level=level):
                result = routed(classifier=lambda _, level=level: classification("implementation", level, delegability=2))
                self.assertEqual(result.execution_strategy, "direct")
                self.assertTrue(result.orchestration_eligible)

    def test_orchestration_eligibility_fails_closed_for_non_codex_two_stage_or_risk(self):
        cases = (
            routed(platform="claude-code", classifier=lambda _: classification("implementation", "L6", delegability=2)),
            routed(classifier=lambda _: classification("architectural_refactoring", "L6", delegability=2)),
            routed(classifier=lambda _: classification("implementation", "L6", delegability=1)),
            routed(classifier=lambda _: classification("implementation", "L6", delegability=2, flags={"public_api_change": True})),
            routed(critical=True, classifier=lambda _: classification("implementation", "L7", delegability=2)),
        )
        for result in cases:
            with self.subTest(result=result):
                self.assertEqual(result.execution_strategy, "direct")
                self.assertFalse(result.orchestration_eligible)

    def test_orchestration_eligibility_fails_closed_for_invalid_policy(self):
        config = json.loads(json.dumps(CONFIG))
        config["orchestration"]["codex"].pop("minimum_delegability")
        result = router.route(
            "task", "codex", config,
            classifier=lambda _: classification("implementation", "L6", delegability=2),
        )
        self.assertFalse(result.orchestration_eligible)

    def test_orchestration_policy_cannot_broaden_the_fixed_safe_floor(self):
        config = json.loads(json.dumps(CONFIG))
        config["orchestration"]["codex"].update(
            eligible_levels=["L1", "L5", "L6", "L7"], minimum_delegability=0,
        )
        result = router.route(
            "task", "codex", config,
            classifier=lambda _: classification("implementation", "L1", delegability=0),
        )
        self.assertFalse(result.orchestration_eligible)

    def test_security_flag_promotes_an_l1_implementation_to_terra(self):
        result = routed(classifier=lambda _: classification("implementation", "L1", flags={"authentication": True}))
        self.assertEqual((result.base_level, result.level), ("L1", "L6"))
        self.assertEqual((result.model, result.effort), ("gpt-5.6-sol", "xhigh"))

    def test_review_with_authorization_routes_sol_xhigh(self):
        result = routed(classifier=lambda _: classification("review", "L2", flags={"authorization": True}))
        self.assertEqual((result.level, result.model, result.effort), ("L6", "gpt-5.6-sol", "xhigh"))

    def test_confidence_bump_conservative_plus_one(self):
        result = routed(classifier=lambda _: classification("implementation", "L3", confidence=0.70))
        self.assertEqual((result.base_level, result.level), ("L4", "L4"))
        self.assertEqual((result.model, result.effort), ("gpt-5.6-terra", "high"))
        self.assertTrue(any("conservative +1 level applied" in r for r in result.rationale))

    def test_critical_override_forces_highest_profile(self):
        result = routed(critical=True)
        self.assertEqual(result.level_name, "critical")
        self.assertEqual((result.model, result.effort), ("gpt-6-astra", "max"))
        self.assertTrue(any("Critical override applied" in r for r in result.rationale))

    def test_explicit_task_type_overrides_the_classified_type_but_not_level(self):
        spy = mock.Mock(return_value=classification("design", "L2"))
        result = routed(explicit_task_type="implementation", classifier=spy)
        spy.assert_called_once()
        self.assertEqual(result.task_type, "implementation")
        self.assertEqual((result.model, result.effort), ("gpt-5.6-luna", "medium"))

    def test_explicit_l5_with_explicit_type_bypasses_the_classifier(self):
        classifier = mock.Mock(side_effect=AssertionError("classifier must be bypassed"))
        result = routed(explicit_level="L7", explicit_task_type="design", classifier=classifier)
        classifier.assert_not_called()
        self.assertEqual(result.level, "L7")
        self.assertEqual(result.task_type, "design")
        self.assertEqual((result.model, result.effort), ("gpt-6-astra", "xhigh"))
        self.assertEqual(result.source, "manual")

    def test_critical_with_explicit_type_bypasses_the_classifier(self):
        classifier = mock.Mock(side_effect=AssertionError("classifier must be bypassed"))
        result = routed(critical=True, explicit_task_type="implementation", classifier=classifier)
        classifier.assert_not_called()
        self.assertEqual(result.level, "critical")
        self.assertEqual(result.task_type, "implementation")
        self.assertEqual((result.model, result.effort), ("gpt-6-astra", "max"))
        self.assertEqual(result.source, "manual")


    def test_explicit_l5_without_a_type_still_classifies_for_the_type_axis(self):
        spy = mock.Mock(return_value=classification("review", "L1"))
        result = routed(explicit_level="L5", classifier=spy)
        spy.assert_called_once()
        self.assertEqual(result.task_type, "review")
        self.assertEqual(result.level, "L5")
        self.assertEqual((result.model, result.effort), ("gpt-5.6-sol", "high"))

    def test_lower_explicit_level_remains_a_minimum_after_preflight(self):
        higher = classification("design", "L5")
        result = routed(platform="claude-code", explicit_level="L2", classifier=lambda _: higher)
        self.assertEqual(result.level, "L5")

    def test_explicit_factors_override_without_lowering_semantic_floor(self):
        spy = mock.Mock(return_value=classification("implementation", "L4"))
        result = routed(explicit_factors={"risk": 0}, classifier=spy)
        spy.assert_called_once()
        self.assertEqual(result.factors["risk"], 0)
        self.assertEqual(result.level, "L4")

    def test_antigravity_available_model_matching(self):
        result = routed(
            platform="antigravity",
            classifier=lambda _: classification("design", "L6"),
            available_models=["Gemini 3.8 Flash (High)", "Claude Opus 4.6 (Thinking)"],
        )
        self.assertEqual(result.model, "Claude Opus 4.6 (Thinking)")
        self.assertIsNone(result.effort)

    def test_antigravity_l5_prefers_31_pro_high(self):
        result = routed(
            platform="antigravity",
            classifier=lambda _: classification("implementation", "L5"),
            available_models=["Gemini 3.8 Flash (High)", "Gemini 3.1 Pro (High)", "Claude Opus 4.6 (Thinking)"],
        )
        self.assertEqual(result.model, "Gemini 3.1 Pro (High)")
        self.assertIsNone(result.effort)

    def test_antigravity_l5_availability_fallback_to_sonnet_thinking(self):
        result = routed(
            platform="antigravity",
            classifier=lambda _: classification("implementation", "L5"),
            available_models=["Gemini 3.8 Flash (High)", "Claude Sonnet 4.6 (Thinking)", "Claude Opus 4.6 (Thinking)"],
        )
        self.assertEqual(result.model, "Claude Sonnet 4.6 (Thinking)")
        self.assertIsNone(result.effort)

    def test_auth_typo_in_readme_does_not_trigger_l6_floor(self):
        # A documentation typo fix mentioning auth should not set security risk flags and should remain L1
        fix = classification("implementation", "L1", flags=NO_FLAGS, confidence=0.98)
        result = routed(task="README에서 auth 설명 오타 수정", classifier=lambda _: fix)
        self.assertEqual(result.level, "L1")
        self.assertFalse(any(result.risk_flags.values()))


    def test_main_reports_a_safe_fallback_on_stderr(self):
        stderr = io.StringIO()
        with mock.patch.object(router, "classify_task", return_value=router.fallback_classification("process failed")):
            with contextlib.redirect_stderr(stderr):
                self.assertEqual(router.main(["--platform", "codex", "--format", "command", "task"]), 0)
        self.assertIn("safe fallback applied", stderr.getvalue())
        self.assertIn("implementation / L3", stderr.getvalue())

    def test_invalid_task_type_is_rejected_by_argparse(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                router.parse_args(["--platform", "codex", "--task-type", "bogus", "task"])


class CommandAndLauncherTests(unittest.TestCase):
    LAUNCHERS = {
        "codex-route": "plugins/codex-model-effort-router/bin/codex-route",
        "claude-route": "plugins/claude-model-effort-router/bin/claude-route",
        "agy-route": "plugins/antigravity-model-effort-router/bin/agy-route",
    }

    def test_single_stage_codex_command_pins_model_and_effort(self):
        result = routed(classifier=lambda _: classification("implementation", "L3"))
        command = router.stage_commands(result, "task")[0]
        self.assertEqual(command[:2], ["codex", "exec"])
        self.assertIn("-m gpt-5.6-terra", " ".join(command[:command.index("task")]))
        self.assertIn("model_reasoning_effort=medium", command)
        self.assertIn("Investigate dependencies and failure paths before editing.", " ".join(command))

    def test_single_stage_commands_include_verification_handoff(self):
        for platform in ("codex", "claude-code", "antigravity"):
            result = routed(
                platform=platform,
                classifier=lambda _: classification("implementation", "L3"),
            )
            command_text = " ".join(router.stage_commands(result, "implement feature")[0])
            self.assertIn(
                "- focused_tests: Code changes need focused regression coverage.",
                command_text,
            )
            self.assertIn(
                "Report each recommended check's result or why it was not run.",
                command_text,
            )
            self.assertIn("Do not report an unrun check as passed", command_text)

    def test_two_stage_only_executor_receives_verification_handoff(self):
        result = routed(classifier=lambda _: classification("architectural_refactoring", "L3"))
        planner, executor = router.stage_commands(result, "restructure modules")
        planner_text, executor_text = " ".join(planner), " ".join(executor)
        self.assertNotIn("focused_tests", planner_text)
        self.assertIn(
            "- focused_tests: Code changes need focused regression coverage.",
            executor_text,
        )
        self.assertIn(
            "- plan_validation: The planner artifact should be validated before execution.",
            executor_text,
        )
        self.assertIn(
            "Report each recommended check's result or why it was not run.",
            executor_text,
        )
        self.assertIn("Do not report an unrun check as passed", executor_text)

    def test_high_risk_verification_recommendations_reach_executor(self):
        result = routed(
            classifier=lambda _: classification(
                "implementation", "L4",
                flags={
                    "authentication": True,
                    "data_migration": True,
                    "public_api_change": True,
                },
            ),
        )
        command_text = " ".join(router.stage_commands(result, "migrate auth API")[0])
        for recommendation in (
            "- security_review: A security, authentication, authorization, or payment risk is active.",
            "- migration_safety: A data migration risk is active.",
            "- contract_review: The route includes a design, review, or public API contract change.",
            "- broad_regression: The effective level requires broad regression coverage.",
        ):
            self.assertIn(recommendation, command_text)

    def test_two_stage_chain_is_success_dependent_and_cleans_up(self):
        result = routed(classifier=lambda _: classification("architectural_refactoring", "L3"))
        chain = router.command_chain(result, "restructure modules")
        self.assertIn("mkdir -p ", chain)
        self.assertIn(" && ", chain)
        self.assertIn("-m gpt-5.6-sol", chain)
        self.assertIn("-m gpt-5.6-terra", chain)
        self.assertIn(str(Path(result.plan_dir) / "plan.json"), chain)
        self.assertIn(f"rm -rf {shlex_quote(str(result.plan_dir))}", chain)
        kept = router.command_chain(result, "restructure modules", keep_plan=True)
        self.assertNotIn("rm -rf", kept)

    def test_two_stage_stage_commands_reference_the_plan_file_twice(self):
        result = routed(classifier=lambda _: classification("architectural_refactoring", "L4"))
        planner, implementer = router.stage_commands(result, "task")
        plan_path = str(Path(result.plan_dir) / "plan.json")
        self.assertEqual(planner[planner.index("-m") + 1], "gpt-5.6-sol")
        self.assertEqual(implementer[implementer.index("-m") + 1], "gpt-5.6-terra")
        joined_planner = " ".join(planner)
        joined_implementer = " ".join(implementer)
        self.assertEqual(joined_planner.count(plan_path), 2)
        self.assertGreaterEqual(joined_implementer.count(plan_path), 1)
        self.assertIn("planning stage", joined_planner)
        self.assertIn("execution stage", joined_implementer)

    def test_json_payload_uses_one_schema_for_both_modes(self):
        single = routed(classifier=lambda _: classification("design", "L2"))
        two = routed(classifier=lambda _: classification("architectural_refactoring", "L3"))
        for result, mode in ((single, "single"), (two, "two_stage")):
            payload = router.result_payload(result, router.stage_commands(result, "task"))
            self.assertEqual(payload["schema_version"], router.SCHEMA_VERSION)
            self.assertEqual(payload["mode"], mode)
            self.assertEqual(len(payload["steps"]), len(result.stages))
            for step in payload["steps"]:
                self.assertIn("command", step)
        first, second = router.result_payload(two, router.stage_commands(two, "task"))["steps"]
        self.assertEqual(first["id"], "plan")
        self.assertEqual(first["depends_on"], [])
        self.assertEqual(second["depends_on"], ["plan"])
        self.assertEqual(first["output"]["path"], second["input"]["path"])

    def test_two_stage_payload_recommends_code_and_plan_checks(self):
        result = routed(classifier=lambda _: classification("architectural_refactoring", "L3"))
        verification = router.result_payload(result, router.stage_commands(result, "task"))["verification"]
        self.assertEqual([check["id"] for check in verification["recommended"]], ["focused_tests", "plan_validation"])
        self.assertEqual(
            [check["id"] for check in verification["skipped"]],
            ["contract_review", "security_review", "migration_safety", "broad_regression"],
        )

    def test_high_risk_payload_recommends_risk_and_contract_checks(self):
        result = routed(
            classifier=lambda _: classification(
                "implementation",
                "L2",
                flags={"authentication": True, "data_migration": True, "public_api_change": True},
            )
        )
        verification = router.result_payload(result, router.stage_commands(result, "task"))["verification"]
        self.assertEqual(
            [check["id"] for check in verification["recommended"]],
            ["focused_tests", "contract_review", "security_review", "migration_safety", "broad_regression"],
        )
        self.assertEqual([check["id"] for check in verification["skipped"]], ["plan_validation"])

    def test_design_payload_recommends_only_contract_review(self):
        result = routed(classifier=lambda _: classification("design", "L2"))
        verification = router.result_payload(result, router.stage_commands(result, "task"))["verification"]
        self.assertEqual([check["id"] for check in verification["recommended"]], ["contract_review"])
        self.assertEqual(
            [check["id"] for check in verification["skipped"]],
            ["focused_tests", "plan_validation", "security_review", "migration_safety", "broad_regression"],
        )

    def test_route_file_replays_json_commands_without_reclassification(self):
        result = routed(classifier=lambda _: classification("review", "L3"))
        payload = router.result_payload(result, router.stage_commands(result, "task"))
        with tempfile.TemporaryDirectory() as tmp:
            route_file = Path(tmp) / "route.json"
            route_file.write_text(json.dumps(payload), encoding="utf-8")
            output = io.StringIO()
            with mock.patch.object(router, "classify_task", side_effect=AssertionError("must not reclassify")):
                with contextlib.redirect_stdout(output):
                    self.assertEqual(router.main(["--route-file", str(route_file)]), 0)
        self.assertIn("codex exec", output.getvalue())
        self.assertIn("gpt-5.6-sol", output.getvalue())

    def test_route_file_replays_v2_without_orchestration_fields(self):
        result = routed(classifier=lambda _: classification("review", "L3"))
        payload = router.result_payload(result, router.stage_commands(result, "task"))
        payload["schema_version"] = 2
        payload.pop("execution_strategy")
        payload.pop("orchestration_eligible")
        with tempfile.TemporaryDirectory() as tmp:
            route_file = Path(tmp) / "route-v2.json"
            route_file.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.object(router, "classify_task", side_effect=AssertionError("must not reclassify")):
                self.assertEqual(router.main(["--route-file", str(route_file)]), 0)

    def test_route_file_rejects_v3_missing_orchestration_contract(self):
        result = routed(classifier=lambda _: classification("review", "L3"))
        payload = router.result_payload(result, router.stage_commands(result, "task"))
        payload.pop("orchestration_eligible")
        with self.assertRaisesRegex(ValueError, "v3 route file"):
            router.command_chain_from_payload(payload)

    def test_route_file_rejects_non_codex_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            route_file = Path(tmp) / "route.json"
            route_file.write_text(json.dumps({"schema_version": router.SCHEMA_VERSION, "platform": "codex", "mode": "single", "steps": [{"command": ["sh", "-c", "bad"]}]}), encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(router.main(["--route-file", str(route_file)]), 2)

    def test_codex_launcher_replays_route_file_without_calling_codex(self):
        result = routed(classifier=lambda _: classification("review", "L3"))
        payload = router.result_payload(result, router.stage_commands(result, "task"))
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            route_file = directory / "route.json"
            route_file.write_text(json.dumps(payload), encoding="utf-8")
            marker = directory / "codex-called"
            fake_codex = directory / "codex"
            fake_codex.write_text(f"#!/bin/sh\ntouch '{marker}'\n", encoding="utf-8")
            fake_codex.chmod(0o755)
            proc = subprocess.run(
                [str(ROOT / self.LAUNCHERS["codex-route"]), "--route-file", str(route_file)],
                capture_output=True,
                text=True,
                timeout=60,
                env={**os.environ, "MODEL_EFFORT_ROUTER_PRINT_ONLY": "1", "PATH": f"{directory}{os.pathsep}{os.environ.get('PATH', '')}"},
            )
            self.assertFalse(marker.exists())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("gpt-5.6-sol", proc.stderr)

    def test_claude_launcher_replays_route_file_without_calling_claude(self):
        result = routed(platform="claude-code", classifier=lambda _: classification("review", "L3"))
        payload = router.result_payload(result, router.stage_commands(result, "task"))
        with tempfile.TemporaryDirectory() as tmp:
            route_file = Path(tmp) / "route.json"
            route_file.write_text(json.dumps(payload), encoding="utf-8")
            proc = subprocess.run(
                [str(ROOT / self.LAUNCHERS["claude-route"]), "--route-file", str(route_file)],
                capture_output=True,
                text=True,
                timeout=60,
                env={**os.environ, "MODEL_EFFORT_ROUTER_PRINT_ONLY": "1"},
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("claude --agent", proc.stderr)

    def test_claude_and_antigravity_launch_the_selected_agent(self):
        for platform in ("claude-code", "antigravity"):
            with self.subTest(platform=platform):
                result = routed(platform=platform, classifier=lambda _: classification("design", "L4"))
                command = router.shell_command(result, "task", False)
                self.assertEqual(command[command.index("--agent") + 1], "level-4-complex")

    def test_claude_effort_omitted_for_haiku(self):
        result_l1 = routed(platform="claude-code", classifier=lambda _: classification("implementation", "L1"))
        self.assertEqual(result_l1.model, "claude-haiku-4-5")
        self.assertIsNone(result_l1.effort)
        command_l1 = router.shell_command(result_l1, "task", False)
        self.assertNotIn("--effort", command_l1)

        result_l3 = routed(platform="claude-code", classifier=lambda _: classification("implementation", "L3"))
        self.assertEqual(result_l3.model, "claude-sonnet-5")
        self.assertEqual(result_l3.effort, "medium")
        command_l3 = router.shell_command(result_l3, "task", False)
        self.assertIn("--effort", command_l3)
        self.assertEqual(command_l3[command_l3.index("--effort") + 1], "medium")

    def test_two_stage_commands_are_platform_native(self):
        for platform, expected_head in (
            ("claude-code", ["claude", "-p", "--model", "claude-fable-5-1"]),
            ("antigravity", ["agy", "--model", "Gemini 3.1 Pro (High)"]),
        ):
            with self.subTest(platform=platform):
                result = routed(platform=platform, classifier=lambda _: classification("architectural_refactoring", "L4"))
                planner, implementer = router.stage_commands(result, "task")
                plan_path = str(Path(result.plan_dir) / "plan.json")
                self.assertEqual(planner[:len(expected_head)], expected_head)
                self.assertGreaterEqual(" ".join(planner).count(plan_path), 1)
                self.assertGreaterEqual(" ".join(implementer).count(plan_path), 1)
                chain = router.command_chain(result, "task")
                self.assertTrue(chain.startswith("mkdir -p "))
                self.assertIn("rm -rf ", chain)

    def test_claude_l6_prefers_fable_when_available(self):
        result = routed(
            platform="claude-code",
            classifier=lambda _: classification("implementation", "L6"),
            available_models=["claude-fable-5-1", "claude-opus-5"],
        )
        self.assertEqual((result.model, result.effort), ("claude-fable-5-1", "high"))

    def test_claude_l6_falls_back_to_opus_when_fable_unavailable(self):
        result = routed(
            platform="claude-code",
            classifier=lambda _: classification("implementation", "L6"),
            available_models=["claude-opus-5", "claude-sonnet-5"],
        )
        self.assertEqual((result.model, result.effort), ("claude-opus-5", "high"))

    def test_claude_critical_prefers_fable_and_falls_back_to_opus(self):
        result_fable = routed(
            platform="claude-code",
            critical=True,
            available_models=["claude-fable-5-1", "claude-opus-5"],
        )
        self.assertEqual((result_fable.model, result_fable.effort), ("claude-fable-5-1", "max"))

        result_opus = routed(
            platform="claude-code",
            critical=True,
            available_models=["claude-opus-5"],
        )
        self.assertEqual((result_opus.model, result_opus.effort), ("claude-opus-5", "max"))

    def test_antigravity_l6_matches_fable_if_available(self):
        result = routed(
            platform="antigravity",
            classifier=lambda _: classification("implementation", "L6"),
            available_models=["Claude Fable 5.1 (Thinking)", "Claude Opus 4.6 (Thinking)"],
        )
        self.assertEqual(result.model, "Claude Fable 5.1 (Thinking)")

    def test_antigravity_l6_falls_back_to_opus_if_fable_unavailable(self):
        result = routed(
            platform="antigravity",
            classifier=lambda _: classification("implementation", "L6"),
            available_models=["Claude Opus 4.6 (Thinking)"],
        )
        self.assertEqual(result.model, "Claude Opus 4.6 (Thinking)")

    def _run_via_symlink(self, name: str, extra_env: dict[str, str] | None = None):
        source = ROOT / self.LAUNCHERS[name]
        fake_payload = classifier_output(task_type="implementation", level="L1", factors={factor: 0 for factor in router.FACTORS})
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            fake_codex = directory / "codex"
            fake_codex.write_text(f"#!/bin/sh\nprintf '%s\\n' '{fake_payload}'\n", encoding="utf-8")
            fake_codex.chmod(0o755)
            wrapped = json.dumps({"structured_output": json.loads(fake_payload)})
            fake_claude = directory / "claude"
            fake_claude.write_text(f"#!/bin/sh\nprintf '%s\\n' '{wrapped}'\n", encoding="utf-8")
            fake_claude.chmod(0o755)
            fake_agy = directory / "agy"
            fake_agy.write_text(f"#!/bin/sh\nprintf '%s\\n' '{wrapped}'\n", encoding="utf-8")
            fake_agy.chmod(0o755)
            link = directory / name
            link.symlink_to(source)
            env = {**os.environ, "MODEL_EFFORT_ROUTER_PRINT_ONLY": "1", "PATH": f"{directory}{os.pathsep}{os.environ.get('PATH', '')}"}
            env.update(extra_env or {})
            return subprocess.run([str(link), "--", "rename one variable"], capture_output=True, text=True, timeout=60, env=env)

    def test_launchers_work_through_symlinks_with_a_fake_preflight(self):
        for name in ("codex-route", "claude-route"):
            with self.subTest(name=name):
                proc = self._run_via_symlink(name)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn("[model-effort-router]", proc.stderr)
        with tempfile.TemporaryDirectory() as tmp:
            models = Path(tmp) / "models.txt"
            models.write_text("Gemini 3.8 Flash (High)\n", encoding="utf-8")
            proc = self._run_via_symlink("agy-route", {"MODEL_EFFORT_ROUTER_MODELS_FILE": str(models)})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Gemini 3.8 Flash (High)", proc.stderr)

    def test_launcher_reports_a_missing_bundle_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run([str(ROOT / self.LAUNCHERS["codex-route"]), "--", "task"], capture_output=True, text=True, timeout=60, env={**os.environ, "MODEL_EFFORT_ROUTER_ROOT": tmp})
        self.assertEqual(proc.returncode, 1)
        self.assertIn("router not found", proc.stderr)


class RouteSkillContractTests(unittest.TestCase):
    def test_readme_documents_the_current_preflight_contract(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("claude-haiku-4-5", readme)
        self.assertNotIn("claude-haiku-4.5", readme)
        self.assertIn("context_required", readme)

    FALLBACK_SENTINELS = (
        "When named-agent delegation is unavailable",
        "When the launcher script cannot start a subprocess",
    )

    def _primary_section(self, plugin: str) -> str:
        path = ROOT / "plugins" / f"{plugin}-model-effort-router" / "skills" / "route" / "SKILL.md"
        primary = path.read_text(encoding="utf-8")
        for sentinel in self.FALLBACK_SENTINELS:
            primary = primary.split(sentinel, 1)[0]
        return " ".join(primary.split())

    def test_named_executors_receive_route_json_and_report_recommended_checks(self):
        for plugin in ("codex", "claude", "antigravity"):
            primary = self._primary_section(plugin)
            with self.subTest(plugin=plugin):
                self.assertIn("complete generated route JSON", primary)
                self.assertIn("every `verification.recommended` ID and reason", primary)
                self.assertIn("report each result or why it was not run", primary)

    def test_claude_skill_replays_stored_steps_for_both_modes(self):
        primary = self._primary_section("claude")
        self.assertIn("bin/claude-route --route-file", primary)
        self.assertIn("steps[].command", primary)
        self.assertIn("matrix `--model` and `--effort`", primary)
        self.assertIn("two_stage", primary)
        self.assertIn("runs the executor only if the plan step succeeds", primary)

    def test_root_and_plugin_docs_describe_v2_v3_replay_contract(self):
        paths = [ROOT / "README.md", ROOT / "references" / "routing-policy.md"]
        for plugin in ("codex", "claude", "antigravity"):
            base = ROOT / "plugins" / f"{plugin}-model-effort-router"
            paths.extend([base / "README.md", base / "skills" / "route" / "SKILL.md"])
        for path in paths:
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                self.assertIn("orchestration_eligible", text)
                self.assertIn("execution_strategy", text)
                self.assertIn("v2", text)

    def test_plugin_readmes_do_not_advertise_stale_preflight_profiles(self):
        codex = (ROOT / "plugins" / "codex-model-effort-router" / "README.md").read_text(encoding="utf-8")
        claude = (ROOT / "plugins" / "claude-model-effort-router" / "README.md").read_text(encoding="utf-8")
        antigravity = (ROOT / "plugins" / "antigravity-model-effort-router" / "README.md").read_text(encoding="utf-8")
        self.assertIn("L1-L7", codex)
        self.assertIn("gpt-5.6-luna` / medium", codex)
        self.assertIn("L6 floor", codex)
        self.assertIn("claude-haiku-4-5", claude)
        self.assertIn("claude-sonnet-5` / medium", claude)
        self.assertIn("Gemini 3.8 Flash (Medium)", antigravity)
        self.assertNotIn("gemini-3.6-flash-low", antigravity)


class ModelDetectionTests(unittest.TestCase):
    def test_detection_passes_a_timeout(self):
        completed = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(router.subprocess, "run", return_value=completed) as run:
            router.read_available_models(timeout=7)
        self.assertEqual(run.call_args.kwargs["timeout"], 7)

    def test_timeout_and_missing_executable_become_runtime_errors(self):
        with mock.patch.object(router.subprocess, "run", side_effect=subprocess.TimeoutExpired("agy", 1)):
            with self.assertRaises(RuntimeError):
                router.read_available_models(timeout=1)
        with self.assertRaises(RuntimeError):
            router.read_available_models(command="model-effort-router-no-such-binary")


class BundleParityTests(unittest.TestCase):
    SHARED = ("scripts/router.py", "config/model-map.json", "references/routing-policy.md")
    PLUGINS = ("plugins/codex-model-effort-router", "plugins/claude-model-effort-router", "plugins/antigravity-model-effort-router")

    def test_plugin_copies_match_the_bundle_root(self):
        for relative in self.SHARED:
            expected = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            for plugin in self.PLUGINS:
                copy = ROOT / plugin / relative
                self.assertTrue(copy.exists(), f"missing copy: {copy}")
                self.assertEqual(hashlib.sha256(copy.read_bytes()).hexdigest(), expected, f"{copy} has drifted from {relative}")

    def test_sync_script_reports_an_already_in_sync_bundle(self):
        proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "sync_bundle.py")], capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)


class PaperthinIntegrationTests(unittest.TestCase):
    def test_readchk_instructions_in_classifier_prompt(self):
        self.assertIn("Apply readchk before scoring", router.CLASSIFIER_PROMPT)
        self.assertIn("restate the core intent internally and resolve referents", router.CLASSIFIER_PROMPT)
        self.assertIn("score ambiguity as 2 and state the surviving fork in reason", router.CLASSIFIER_PROMPT)

    def test_re0_and_debloat_in_two_stage_templates(self):
        self.assertIn("Apply re0 and debloat principles", router.PLANNER_INSTRUCTIONS_TEMPLATE)
        self.assertIn("clean v0 specification without speculative boilerplate", router.PLANNER_INSTRUCTIONS_TEMPLATE)
        self.assertIn("Cut words, keep rules", router.PLANNER_INSTRUCTIONS_TEMPLATE)
        self.assertIn("Apply re0 hygiene", router.IMPLEMENTER_INSTRUCTIONS_TEMPLATE)
        self.assertIn("leave the codebase cleaner than found", router.IMPLEMENTER_INSTRUCTIONS_TEMPLATE)

    def test_autobahn_scope_guard_injected_when_security_flags_active(self):
        result_sec = routed(classifier=lambda _: classification("implementation", "L1", flags={"security_sensitive": True}))
        command = router.stage_commands(result_sec, "fix payment")[0]
        self.assertIn("Autobahn scope guard", " ".join(command))

        payload_sec = router.result_payload(result_sec, [command])
        self.assertIn("scope_guard", payload_sec)
        self.assertEqual(payload_sec["scope_guard"]["policy"], "autobahn_scope_carve")
        self.assertIn("security_sensitive", payload_sec["scope_guard"]["risk_flags"])

        result_normal = routed(classifier=lambda _: classification("implementation", "L1"))
        command_normal = router.stage_commands(result_normal, "simple task")[0]
        self.assertNotIn("Autobahn scope guard", " ".join(command_normal))
        payload_normal = router.result_payload(result_normal, [command_normal])
        self.assertNotIn("scope_guard", payload_normal)

    def test_autobahn_scope_guard_in_two_stage_execution(self):
        result_two_sec = routed(classifier=lambda _: classification("architectural_refactoring", "L3", flags={"authentication": True}))
        planner, implementer = router.stage_commands(result_two_sec, "refactor auth")
        self.assertIn("Autobahn scope guard", " ".join(planner))
        self.assertIn("Autobahn scope guard", " ".join(implementer))

    def test_autobahn_scope_guard_in_claude_and_antigravity_single_stage(self):
        for platform in ("claude-code", "antigravity"):
            with self.subTest(platform=platform):
                result_sec = routed(platform=platform, classifier=lambda _: classification("implementation", "L1", flags={"security_sensitive": True}))
                command = router.stage_commands(result_sec, "fix auth bug")[0]
                self.assertIn("Autobahn scope guard", " ".join(command))

                result_normal = routed(platform=platform, classifier=lambda _: classification("implementation", "L1"))
                command_normal = router.stage_commands(result_normal, "fix bug")[0]
                self.assertNotIn("Autobahn scope guard", " ".join(command_normal))

    def test_autobahn_scope_guard_dry_constant(self):
        self.assertTrue(router.AUTOBAHN_SCOPE_GUARD.endswith(router.AUTOBAHN_SCOPE_GUARD_INSTRUCTION))


def shlex_quote(value: str) -> str:
    import shlex

    return shlex.quote(value)


if __name__ == "__main__":
    unittest.main()

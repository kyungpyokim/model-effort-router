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


def classifier_output(task_type="implementation", level="L2", factors=None, flags=None, confidence=0.9, reason="Clear scoped change.", raw=True):
    payload = {
        "task_type": task_type,
        "level": level,
        "factors": dict(factors or BASE_FACTORS),
        "risk_flags": {**NO_FLAGS, **(flags or {})},
        "confidence": confidence,
        "reason": reason,
    }
    return json.dumps(payload) if raw else payload


def classification(task_type="implementation", level="L2", factors=None, flags=None, source="terra"):
    return router.Classification(
        task_type=task_type,
        level=level,
        factors=dict(factors or BASE_FACTORS),
        risk_flags={**NO_FLAGS, **(flags or {})},
        confidence=0.9,
        reason="classified",
        source=source,
    )


def routed(task="task", platform="codex", explicit_level=None, explicit_task_type=None,
           explicit_factors=None, available_models=None, classifier=None):
    return router.route(
        task, platform, CONFIG,
        explicit_factors=explicit_factors,
        explicit_level=explicit_level,
        explicit_task_type=explicit_task_type,
        available_models=available_models,
        classifier=classifier or (lambda _: classification()),
    )


class PlatformClassifierTests(unittest.TestCase):
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
        self.assertEqual(command[command.index("--model") + 1], "gpt-5.6-terra")
        self.assertEqual(captured["schema"]["properties"]["task_type"]["enum"], list(router.TASK_TYPES))
        self.assertEqual(captured["schema"]["properties"]["risk_flags"]["required"], list(router.RISK_FLAGS))
        self.assertNotIn("hard_floor", captured["schema"]["properties"])
        self.assertEqual(result.source, "terra")
        self.assertEqual(run.call_args.kwargs["timeout"], 7)

    def test_claude_uses_native_structured_output_without_tools_or_session(self):
        completed = subprocess.CompletedProcess([], 0, json.dumps({"structured_output": json.loads(classifier_output())}), "")
        with mock.patch.object(router.subprocess, "run", return_value=completed) as run:
            result = router.classify_task("add a settings page", platform="claude-code", timeout=7)
        command = run.call_args.args[0]
        self.assertEqual(command[:2], ["claude", "-p"])
        self.assertEqual(json.loads(command[command.index("--json-schema") + 1]), router.CLASSIFIER_SCHEMA)
        self.assertEqual(result.source, "claude-sonnet-5")
        self.assertTrue(Path(run.call_args.kwargs["cwd"]).name.startswith("model-effort-router-"))

    def test_antigravity_uses_isolated_structured_json_classifier(self):
        completed = subprocess.CompletedProcess([], 0, json.dumps({"structured_output": json.loads(classifier_output())}), "")
        with mock.patch.object(router.subprocess, "run", return_value=completed) as run:
            result = router.classify_task("task", platform="antigravity", timeout=7)
        command = run.call_args.args[0]
        self.assertEqual(command[:2], ["agy", "--print"])
        self.assertEqual(json.loads(command[command.index("--json-schema") + 1]), router.CLASSIFIER_SCHEMA)
        self.assertEqual(result.source, "gemini-3.6-flash-low")

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
            lambda p: p.update(reason=""),
        ):
            payload = json.loads(json.dumps(valid))
            mutation(payload)
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError):
                    router.validate_classifier_output(payload)
        self.assertEqual(router.validate_classifier_output(valid).task_type, "implementation")

    def test_timeouts_must_be_finite_and_positive(self):
        for option in ("--classifier-timeout", "--detect-timeout"):
            for value in ("0", "-1", "nan", "inf"):
                with self.subTest(option=option, value=value), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        router.parse_args(["--platform", "codex", option, value, "task"])


class EscalationTests(unittest.TestCase):
    def test_security_flags_force_an_l4_floor(self):
        cases = (
            ("L1", {"authentication": True}, "L4"),
            ("L2", {"payment": True}, "L4"),
            ("L3", {"authorization": True}, "L4"),
            ("L1", {"security_sensitive": True}, "L4"),
            ("L5", {"security_sensitive": True}, "L5"),
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
        self.assertEqual(router.apply_risk_escalation("L5", {**NO_FLAGS, "data_migration": True}), "L5")

    def test_no_flags_keeps_the_base_level(self):
        self.assertEqual(router.apply_risk_escalation("L2", NO_FLAGS), "L2")


class MatrixTests(unittest.TestCase):
    EXPECTED_SINGLE = {
        ("implementation", "L1"): ("gpt-5.6-luna", "medium"),
        ("implementation", "L2"): ("gpt-5.6-luna", "high"),
        ("implementation", "L3"): ("gpt-5.6-luna", "xhigh"),
        ("implementation", "L4"): ("gpt-5.6-terra", "xhigh"),
        ("implementation", "L5"): ("gpt-5.6-terra", "max"),
        ("local_refactoring", "L1"): ("gpt-5.6-luna", "medium"),
        ("local_refactoring", "L2"): ("gpt-5.6-luna", "high"),
        ("local_refactoring", "L3"): ("gpt-5.6-luna", "xhigh"),
        ("local_refactoring", "L4"): ("gpt-5.6-terra", "xhigh"),
        ("local_refactoring", "L5"): ("gpt-5.6-terra", "max"),
        ("design", "L1"): ("gpt-5.6-sol", "low"),
        ("design", "L2"): ("gpt-5.6-sol", "medium"),
        ("design", "L3"): ("gpt-5.6-sol", "high"),
        ("design", "L4"): ("gpt-5.6-sol", "xhigh"),
        ("design", "L5"): ("gpt-5.6-sol", "max"),
        ("review", "L1"): ("gpt-5.6-sol", "low"),
        ("review", "L2"): ("gpt-5.6-sol", "medium"),
        ("review", "L3"): ("gpt-5.6-sol", "high"),
        ("review", "L4"): ("gpt-5.6-sol", "xhigh"),
        ("review", "L5"): ("gpt-5.6-sol", "max"),
        ("architectural_refactoring", "L1"): ("gpt-5.6-sol", "medium"),
        ("architectural_refactoring", "L2"): ("gpt-5.6-sol", "high"),
    }
    EXPECTED_STAGES = {
        ("architectural_refactoring", "L3"): [("planner", "gpt-5.6-sol", "high"), ("implementer", "gpt-5.6-luna", "xhigh")],
        ("architectural_refactoring", "L4"): [("planner", "gpt-5.6-sol", "xhigh"), ("implementer", "gpt-5.6-terra", "xhigh")],
        ("architectural_refactoring", "L5"): [("planner", "gpt-5.6-sol", "max"), ("implementer", "gpt-5.6-terra", "max")],
    }

    def test_every_matrix_cell_matches_the_final_spec(self):
        for task_type in router.TASK_TYPES:
            for level in router.LEVELS:
                with self.subTest(cell=f"{task_type}/{level}"):
                    result = routed(classifier=lambda _, t=task_type, l=level: classification(t, l))
                    self.assertEqual(result.task_type, task_type)
                    self.assertEqual(result.level, level)
                    if (task_type, level) in self.EXPECTED_SINGLE:
                        model, effort = self.EXPECTED_SINGLE[(task_type, level)]
                        self.assertEqual(result.mode, "single")
                        self.assertEqual((result.model, result.effort), (model, effort))
                        self.assertIsNone(result.plan_dir)
                    else:
                        expected = self.EXPECTED_STAGES[(task_type, level)]
                        self.assertEqual(result.mode, "two_stage")
                        self.assertIsNone(result.model)
                        self.assertIsNone(result.effort)
                        self.assertIsNotNone(result.plan_dir)
                        self.assertEqual([(s["role"], s["model"], s["effort"]) for s in result.stages], expected)


class RoutingTests(unittest.TestCase):
    def test_security_flag_promotes_an_l1_implementation_to_terra(self):
        result = routed(classifier=lambda _: classification("implementation", "L1", flags={"authentication": True}))
        self.assertEqual((result.base_level, result.level), ("L1", "L4"))
        self.assertEqual((result.model, result.effort), ("gpt-5.6-terra", "xhigh"))

    def test_review_with_authorization_routes_sol_xhigh(self):
        result = routed(classifier=lambda _: classification("review", "L2", flags={"authorization": True}))
        self.assertEqual((result.level, result.model, result.effort), ("L4", "gpt-5.6-sol", "xhigh"))

    def test_explicit_task_type_overrides_the_classified_type_but_not_level(self):
        spy = mock.Mock(return_value=classification("design", "L2"))
        result = routed(explicit_task_type="implementation", classifier=spy)
        spy.assert_called_once()
        self.assertEqual(result.task_type, "implementation")
        self.assertEqual((result.model, result.effort), ("gpt-5.6-luna", "high"))

    def test_explicit_l5_with_explicit_type_bypasses_the_classifier(self):
        classifier = mock.Mock(side_effect=AssertionError("classifier must be bypassed"))
        result = routed(explicit_level="L5", explicit_task_type="design", classifier=classifier)
        classifier.assert_not_called()
        self.assertEqual(result.level, "L5")
        self.assertEqual(result.task_type, "design")
        self.assertEqual((result.model, result.effort), ("gpt-5.6-sol", "max"))
        self.assertEqual(result.source, "manual")

    def test_explicit_l5_without_a_type_still_classifies_for_the_type_axis(self):
        spy = mock.Mock(return_value=classification("review", "L1"))
        result = routed(explicit_level="L5", classifier=spy)
        spy.assert_called_once()
        self.assertEqual(result.task_type, "review")
        self.assertEqual(result.level, "L5")
        self.assertEqual((result.model, result.effort), ("gpt-5.6-sol", "max"))

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
            classifier=lambda _: classification("design", "L5"),
            available_models=["Gemini 3.5 Flash (Low)", "Claude Opus 4.6 (Thinking)"],
        )
        self.assertEqual(result.model, "Claude Opus 4.6 (Thinking)")
        self.assertIsNone(result.effort)

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
        self.assertIn("-m gpt-5.6-luna", " ".join(command[:command.index("task")]))
        self.assertIn("model_reasoning_effort=xhigh", command)
        self.assertIn("Investigate dependencies and failure paths before editing.", " ".join(command))

    def test_two_stage_chain_is_success_dependent_and_cleans_up(self):
        result = routed(classifier=lambda _: classification("architectural_refactoring", "L3"))
        chain = router.command_chain(result, "restructure modules")
        self.assertIn("mkdir -p ", chain)
        self.assertIn(" && ", chain)
        self.assertIn("-m gpt-5.6-sol", chain)
        self.assertIn("-m gpt-5.6-luna", chain)
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

    def test_claude_and_antigravity_launch_the_selected_agent(self):
        for platform in ("claude-code", "antigravity"):
            with self.subTest(platform=platform):
                result = routed(platform=platform, classifier=lambda _: classification("design", "L4"))
                command = router.shell_command(result, "task", False)
                self.assertEqual(command[command.index("--agent") + 1], "level-4-advanced")

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
            models.write_text("Gemini 3.5 Flash (Low)\n", encoding="utf-8")
            proc = self._run_via_symlink("agy-route", {"MODEL_EFFORT_ROUTER_MODELS_FILE": str(models)})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Gemini 3.5 Flash (Low)", proc.stderr)

    def test_launcher_reports_a_missing_bundle_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run([str(ROOT / self.LAUNCHERS["codex-route"]), "--", "task"], capture_output=True, text=True, timeout=60, env={**os.environ, "MODEL_EFFORT_ROUTER_ROOT": tmp})
        self.assertEqual(proc.returncode, 1)
        self.assertIn("router not found", proc.stderr)


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


def shlex_quote(value: str) -> str:
    import shlex

    return shlex.quote(value)


if __name__ == "__main__":
    unittest.main()

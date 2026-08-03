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


def terra_output(level="L2", factors=None, rationale=None):
    return json.dumps({
        "level": level,
        "factors": factors or {"scope": 1, "ambiguity": 0, "diagnosis": 0, "design": 1, "risk": 0, "verification": 1},
        "rationale": rationale or ["Clear feature with focused verification."],
        "hard_floor": None,
    })


class PlatformClassifierTests(unittest.TestCase):
    def test_uses_fixed_low_effort_terra_with_schema(self):
        completed = subprocess.CompletedProcess([], 0, terra_output(), "")
        captured = {}

        def run_classifier(command, **kwargs):
            captured["schema"] = json.loads(Path(command[command.index("--output-schema") + 1]).read_text(encoding="utf-8"))
            return completed

        with mock.patch.object(router.subprocess, "run", side_effect=run_classifier) as run:
            result = router.classify_task("add a settings page", timeout=7)
        command = run.call_args.args[0]
        self.assertEqual(command[0:2], ["codex", "exec"])
        self.assertIn("--ephemeral", command)
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--ignore-rules", command)
        self.assertIn("read-only", command)
        self.assertEqual(command[command.index("--cd") + 1], str(Path(command[command.index("--output-schema") + 1]).parent))
        self.assertIn("--skip-git-repo-check", command)
        self.assertEqual(command[command.index("--model") + 1], "gpt-5.6-terra")
        self.assertEqual(command[command.index("--config") + 1], 'model_reasoning_effort="low"')
        self.assertEqual(captured["schema"]["properties"]["level"]["enum"], list(router.LEVELS))
        self.assertEqual(result.source, "terra")
        self.assertEqual(run.call_args.kwargs["timeout"], 7)
        self.assertEqual(run.call_args.kwargs["cwd"], command[command.index("--cd") + 1])

    def test_claude_uses_native_structured_output_without_tools_or_session(self):
        completed = subprocess.CompletedProcess([], 0, json.dumps({"structured_output": json.loads(terra_output())}), "")
        with mock.patch.object(router.subprocess, "run", return_value=completed) as run:
            result = router.classify_task("add a settings page", platform="claude-code", timeout=7)
        command = run.call_args.args[0]
        self.assertEqual(command[:2], ["claude", "-p"])
        self.assertEqual(command[command.index("--model") + 1], "claude-sonnet-5")
        self.assertEqual(command[command.index("--effort") + 1], "low")
        self.assertEqual(command[command.index("--output-format") + 1], "json")
        self.assertEqual(json.loads(command[command.index("--json-schema") + 1]), router.CLASSIFIER_SCHEMA)
        self.assertIn("--safe-mode", command)
        self.assertEqual(command[command.index("--tools") + 1], "")
        self.assertEqual(command[command.index("--permission-mode") + 1], "plan")
        self.assertIn("--no-session-persistence", command)
        self.assertNotIn("--setting-sources", command)
        self.assertNotIn("--strict-mcp-config", command)
        self.assertEqual(result.source, "claude-sonnet-5")
        self.assertTrue(Path(run.call_args.kwargs["cwd"]).name.startswith("model-effort-router-"))

    def test_antigravity_uses_isolated_structured_json_classifier(self):
        completed = subprocess.CompletedProcess([], 0, json.dumps({"structured_output": json.loads(terra_output())}), "")
        with mock.patch.object(router.subprocess, "run", return_value=completed) as run:
            result = router.classify_task("add a settings page", platform="antigravity", timeout=7)
        command = run.call_args.args[0]
        self.assertEqual(command[:2], ["agy", "--print"])
        self.assertEqual(command[command.index("--model") + 1], "gemini-3.6-flash-low")
        self.assertEqual(command[command.index("--effort") + 1], "low")
        self.assertEqual(command[command.index("--mode") + 1], "plan")
        self.assertIn("--sandbox", command)
        self.assertIn("--disable-slash-commands", command)
        self.assertEqual(command[command.index("--output-format") + 1], "json")
        self.assertEqual(json.loads(command[command.index("--json-schema") + 1]), router.CLASSIFIER_SCHEMA)
        self.assertEqual(result.source, "gemini-3.6-flash-low")
        self.assertTrue(Path(run.call_args.kwargs["cwd"]).name.startswith("model-effort-router-"))

    def test_claude_requires_the_documented_structured_output_wrapper(self):
        completed = subprocess.CompletedProcess([], 0, terra_output(), "")
        with mock.patch.object(router.subprocess, "run", return_value=completed):
            result = router.classify_task("task", platform="claude-code")
        self.assertEqual((result.level, result.source), ("L3", "fallback"))

    def test_timeout_process_failure_and_invalid_output_fall_back_to_l3(self):
        cases = (
            subprocess.TimeoutExpired("codex", 1),
            OSError("missing executable"),
            subprocess.CompletedProcess([], 1, "", "failed"),
            subprocess.CompletedProcess([], 0, '{"level":"L2"}', ""),
        )
        for outcome in cases:
            with self.subTest(outcome=type(outcome).__name__):
                with mock.patch.object(router.subprocess, "run", side_effect=outcome if isinstance(outcome, Exception) else None, return_value=None if isinstance(outcome, Exception) else outcome):
                    result = router.classify_task("task")
                self.assertEqual(result.level, "L3")
                self.assertEqual(result.source, "fallback")
                self.assertEqual(result.factors, {factor: 1 for factor in router.FACTORS})

    def test_schema_validation_rejects_extra_missing_and_bad_values(self):
        for payload in (
            {"level": "L2", "factors": {}, "rationale": ["x"]},
            {"level": "L9", "factors": {factor: 0 for factor in router.FACTORS}, "rationale": ["x"], "hard_floor": None},
            {"level": "L2", "factors": {factor: 0 for factor in router.FACTORS}, "rationale": [], "hard_floor": None},
            {"level": "L2", "factors": {factor: 0 for factor in router.FACTORS}, "rationale": ["x"], "hard_floor": None, "extra": True},
            {"level": "L1", "factors": {factor: 1 for factor in router.FACTORS}, "rationale": ["x"], "hard_floor": None},
            {"level": "L2", "factors": {factor: 0 for factor in router.FACTORS}, "rationale": ["x"], "hard_floor": "L4"},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    router.validate_classifier_output(payload)

        valid_l1 = {
            "level": "L1",
            "factors": {factor: 2 if factor == "scope" else 0 for factor in router.FACTORS},
            "rationale": ["One contained but substantial edit."],
            "hard_floor": None,
        }
        self.assertEqual(router.validate_classifier_output(valid_l1).level, "L1")

    def test_timeouts_must_be_finite_and_positive(self):
        for option in ("--classifier-timeout", "--detect-timeout"):
            for value in ("0", "-1", "nan", "inf"):
                with self.subTest(option=option, value=value), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        router.parse_args(["--platform", "codex", option, value, "task"])


class RoutingTests(unittest.TestCase):
    def test_classifier_route_uses_classified_level(self):
        classification = router.Classification("L4", {factor: 1 for factor in router.FACTORS}, ["security-sensitive change"], "terra")
        result = router.route("change auth", "codex", CONFIG, classifier=lambda _: classification)
        self.assertEqual((result.level, result.model, result.effort, result.source), ("L4", "gpt-5.6-sol", "xhigh", "terra"))

    def test_explicit_l5_bypasses_classifier(self):
        classifier = mock.Mock(side_effect=AssertionError("classifier must be bypassed"))
        result = router.route("rename", "codex", CONFIG, explicit_level="L5", classifier=classifier)
        self.assertEqual(result.level, "L5")
        classifier.assert_not_called()

    def test_lower_explicit_level_remains_a_minimum_after_preflight(self):
        higher = router.Classification("L5", {factor: 2 for factor in router.FACTORS}, ["critical"], "terra")
        result = router.route("task", "claude-code", CONFIG, explicit_level="L2", classifier=lambda _: higher)
        self.assertEqual(result.level, "L5")

    def test_explicit_factors_override_terra_without_lowering_its_floor(self):
        classification = router.Classification("L4", {factor: 1 for factor in router.FACTORS}, ["security-sensitive"], "terra")
        classifier = mock.Mock(return_value=classification)
        result = router.route("task", "claude-code", CONFIG, explicit_factors={"risk": 0}, classifier=classifier)
        self.assertEqual(result.factors["risk"], 0)
        self.assertEqual(result.level, "L4")
        classifier.assert_called_once()

    def test_explicit_level_is_a_minimum_with_factor_overrides(self):
        classification = router.Classification("L3", {factor: 1 for factor in router.FACTORS}, ["complex"], "terra")
        result = router.route("task", "claude-code", CONFIG, explicit_factors={factor: 2 for factor in router.FACTORS}, explicit_level="L2", classifier=lambda _: classification)
        self.assertEqual(result.level, "L5")

    def test_antigravity_available_model_matching(self):
        classification = router.Classification("L5", {factor: 2 for factor in router.FACTORS}, ["critical"], "terra")
        result = router.route("task", "antigravity", CONFIG, available_models=["Gemini 3.5 Flash (Low)", "Claude Opus 4.6 (Thinking)"], classifier=lambda _: classification)
        self.assertEqual(result.model, "Claude Opus 4.6 (Thinking)")
        self.assertIsNone(result.effort)

    def test_main_reports_a_safe_fallback_on_stderr(self):
        fallback = router.fallback_classification("process failed")
        stderr = io.StringIO()
        with mock.patch.object(router, "classify_task", return_value=fallback):
            with contextlib.redirect_stderr(stderr):
                self.assertEqual(router.main(["--platform", "codex", "--format", "command", "task"]), 0)
        self.assertIn("safe L3 fallback applied", stderr.getvalue())


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

    def test_antigravity_uses_fallback_when_no_account_models_are_available(self):
        classification = router.Classification("L5", {factor: 2 for factor in router.FACTORS}, ["critical"], "terra", "L5")
        result = router.route("task", "antigravity", CONFIG, classifier=lambda _: classification)
        self.assertEqual(result.model, CONFIG["platforms"]["antigravity"]["L5"]["fallback"])
        self.assertEqual(result.hard_floor, "L5")


class CommandAndLauncherTests(unittest.TestCase):
    LAUNCHERS = {
        "codex-route": "plugins/codex-model-effort-router/bin/codex-route",
        "claude-route": "plugins/claude-model-effort-router/bin/claude-route",
        "agy-route": "plugins/antigravity-model-effort-router/bin/agy-route",
    }

    def test_shell_command_keeps_platform_specific_arguments(self):
        classification = router.Classification("L4", {factor: 1 for factor in router.FACTORS}, ["advanced"], "terra", "L4")
        result = router.route("task", "codex", CONFIG, classifier=lambda _: classification)
        command = router.shell_command(result, "task", False)
        self.assertEqual(command[:2], ["codex", "exec"])
        self.assertIn("model_reasoning_effort=xhigh", command)
        self.assertIn("Prioritize correctness and blast-radius control.", " ".join(command))

    def test_claude_and_antigravity_launch_the_selected_agent(self):
        classification = router.Classification("L4", {factor: 1 for factor in router.FACTORS}, ["advanced"], "terra", "L4")
        for platform in ("claude-code", "antigravity"):
            with self.subTest(platform=platform):
                result = router.route("task", platform, CONFIG, classifier=lambda _: classification)
                command = router.shell_command(result, "task", False)
                self.assertEqual(command[command.index("--agent") + 1], "level-4-advanced")

    def _run_via_symlink(self, name: str, extra_env: dict[str, str] | None = None):
        source = ROOT / self.LAUNCHERS[name]
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            fake_codex = directory / "codex"
            fake_codex.write_text("#!/bin/sh\nprintf '%s\\n' '{\"level\":\"L1\",\"factors\":{\"scope\":0,\"ambiguity\":0,\"diagnosis\":0,\"design\":0,\"risk\":0,\"verification\":0},\"rationale\":[\"simple\"],\"hard_floor\":null}'\n", encoding="utf-8")
            fake_codex.chmod(0o755)
            fake_claude = directory / "claude"
            fake_claude.write_text("#!/bin/sh\nprintf '%s\\n' '{\"structured_output\":{\"level\":\"L1\",\"factors\":{\"scope\":0,\"ambiguity\":0,\"diagnosis\":0,\"design\":0,\"risk\":0,\"verification\":0},\"rationale\":[\"simple\"],\"hard_floor\":null}}'\n", encoding="utf-8")
            fake_claude.chmod(0o755)
            fake_agy = directory / "agy"
            fake_agy.write_text("#!/bin/sh\nprintf '%s\\n' '{\"structured_output\":{\"level\":\"L1\",\"factors\":{\"scope\":0,\"ambiguity\":0,\"diagnosis\":0,\"design\":0,\"risk\":0,\"verification\":0},\"rationale\":[\"simple\"],\"hard_floor\":null}}'\n", encoding="utf-8")
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


if __name__ == "__main__":
    unittest.main()

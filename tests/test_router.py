from pathlib import Path
from unittest import mock
import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
import sys

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("router", ROOT / "scripts" / "router.py")
router = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = router
SPEC.loader.exec_module(router)
CONFIG = router.load_config(ROOT / "config" / "model-map.json")


class RouterTests(unittest.TestCase):
    def test_simple_task(self):
        result = router.route("버튼 문구 오탈자 수정", "codex", CONFIG)
        self.assertEqual(result.level, "L1")
        self.assertEqual(result.model, "gpt-5.6-luna")
        self.assertEqual(result.effort, "low")

    def test_standard_feature(self):
        result = router.route(
            "새 API endpoint 기능을 구현하고 unit test 추가",
            "claude-code",
            CONFIG,
            explicit_factors={"scope": 1, "ambiguity": 0, "diagnosis": 0, "design": 1, "risk": 1, "verification": 1},
        )
        self.assertEqual(result.level, "L2")
        self.assertEqual(result.model, "sonnet")
        self.assertEqual(result.effort, "medium")

    def test_security_floor(self):
        result = router.route("OAuth 인증 보안 로직 변경", "codex", CONFIG)
        self.assertIn(result.level, ("L4", "L5"))
        self.assertEqual(result.model, "gpt-5.6-sol")

    def test_critical_floor(self):
        result = router.route("운영 financial ledger 데이터 삭제 마이그레이션", "claude-code", CONFIG)
        self.assertEqual(result.level, "L5")
        self.assertEqual(result.model, "opus")
        self.assertEqual(result.effort, "max")

    def test_antigravity_available_model_matching(self):
        available = [
            "Gemini 3.5 Flash (Low)",
            "Gemini 3.5 Flash (High)",
            "Claude Opus 4.6 (Thinking)",
        ]
        result = router.route(
            "critical cryptography protocol design",
            "antigravity",
            CONFIG,
            available_models=available,
        )
        self.assertEqual(result.level, "L5")
        self.assertEqual(result.model, "Claude Opus 4.6 (Thinking)")
        self.assertIsNone(result.effort)

    def test_explicit_level_never_lowers(self):
        result = router.route("rename one variable", "codex", CONFIG, explicit_level="L4")
        self.assertEqual(result.level, "L4")


TASK_WITH_MANY_SIGNALS = "간헐적 race condition 으로 여러 서비스 장애 근본 원인 분석 및 e2e 회귀 테스트"


class ExplicitFactorTests(unittest.TestCase):
    """Regression tests: a partially supplied factor must not zero the rest."""

    def test_partial_factors_keep_keyword_scores(self):
        baseline = router.route(TASK_WITH_MANY_SIGNALS, "codex", CONFIG)
        partial = router.route(
            TASK_WITH_MANY_SIGNALS, "codex", CONFIG, explicit_factors={"scope": 2}
        )
        self.assertEqual(partial.factors["scope"], 2)
        for factor in ("diagnosis", "verification"):
            self.assertEqual(
                partial.factors[factor],
                baseline.factors[factor],
                f"{factor} was silently discarded by a partial override",
            )
        self.assertGreaterEqual(partial.score, baseline.score)

    def test_partial_factor_cannot_lower_the_level(self):
        baseline = router.route(TASK_WITH_MANY_SIGNALS, "codex", CONFIG)
        partial = router.route(
            TASK_WITH_MANY_SIGNALS, "codex", CONFIG, explicit_factors={"scope": 2}
        )
        self.assertEqual(router.higher_level(partial.level, baseline.level), partial.level)

    def test_explicit_factor_overrides_the_keyword_value(self):
        result = router.route(
            "간헐적 race condition 디버깅", "codex", CONFIG, explicit_factors={"diagnosis": 0}
        )
        self.assertEqual(result.factors["diagnosis"], 0)

    def test_full_explicit_factor_set_still_wins(self):
        result = router.route(
            TASK_WITH_MANY_SIGNALS,
            "codex",
            CONFIG,
            explicit_factors={f: 0 for f in router.FACTORS},
        )
        self.assertEqual(result.score, 0)

    def test_out_of_range_factor_is_rejected(self):
        with self.assertRaises(ValueError):
            router.route("simple task", "codex", CONFIG, explicit_factors={"scope": 3})


class ModelDetectionTests(unittest.TestCase):
    """Regression tests: model detection must not hang or leak raw exceptions."""

    def test_detection_passes_a_timeout(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with mock.patch.object(router.subprocess, "run", return_value=completed) as run:
            router.read_available_models(timeout=7)
        self.assertEqual(run.call_args.kwargs.get("timeout"), 7)

    def test_timeout_becomes_runtimeerror(self):
        expired = subprocess.TimeoutExpired(cmd="agy models", timeout=1)
        with mock.patch.object(router.subprocess, "run", side_effect=expired):
            with self.assertRaises(RuntimeError) as ctx:
                router.read_available_models(timeout=1)
        self.assertIn("timed out", str(ctx.exception))

    def test_missing_executable_becomes_runtimeerror(self):
        with self.assertRaises(RuntimeError):
            router.read_available_models(command="model-effort-router-no-such-binary")

    def test_route_falls_back_when_no_models_detected(self):
        result = router.route("irreversible cryptography compliance", "antigravity", CONFIG, available_models=None)
        self.assertEqual(result.level, "L5")
        self.assertEqual(result.model, CONFIG["platforms"]["antigravity"]["L5"]["fallback"])


class LauncherTests(unittest.TestCase):
    """Regression tests: launchers must resolve the bundle through a symlink."""

    LAUNCHERS = {
        "codex-route": "plugins/codex-model-effort-router/bin/codex-route",
        "claude-route": "plugins/claude-model-effort-router/bin/claude-route",
        "agy-route": "plugins/antigravity-model-effort-router/bin/agy-route",
    }

    def _run_via_symlink(self, name: str, extra_env: dict[str, str] | None = None):
        source = ROOT / self.LAUNCHERS[name]
        with tempfile.TemporaryDirectory() as tmp:
            link = Path(tmp) / name
            link.symlink_to(source)
            env = {**os.environ, "MODEL_EFFORT_ROUTER_PRINT_ONLY": "1"}
            env.update(extra_env or {})
            return subprocess.run(
                [str(link), "--", "rename one variable"],
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
            )

    def test_codex_launcher_works_through_a_symlink(self):
        proc = self._run_via_symlink("codex-route")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("codex", proc.stderr)
        self.assertNotIn("router not found", proc.stderr)

    def test_claude_launcher_works_through_a_symlink(self):
        proc = self._run_via_symlink("claude-route")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("--effort", proc.stderr)

    def test_agy_launcher_works_through_a_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            models = Path(tmp) / "models.txt"
            models.write_text("Gemini 3.5 Flash (Low)\n", encoding="utf-8")
            proc = self._run_via_symlink(
                "agy-route", {"MODEL_EFFORT_ROUTER_MODELS_FILE": str(models)}
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Gemini 3.5 Flash (Low)", proc.stderr)

    def test_launcher_reports_a_missing_bundle_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [str(ROOT / self.LAUNCHERS["codex-route"]), "--", "task"],
                capture_output=True,
                text=True,
                timeout=60,
                env={**os.environ, "MODEL_EFFORT_ROUTER_ROOT": tmp},
            )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("router not found", proc.stderr)


class BundleParityTests(unittest.TestCase):
    """The bundle ships verbatim copies; they must not drift apart."""

    SHARED = (
        "scripts/router.py",
        "config/model-map.json",
        "references/routing-policy.md",
    )
    PLUGINS = (
        "plugins/codex-model-effort-router",
        "plugins/claude-model-effort-router",
        "plugins/antigravity-model-effort-router",
    )

    def test_plugin_copies_match_the_bundle_root(self):
        for relative in self.SHARED:
            expected = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            for plugin in self.PLUGINS:
                copy = ROOT / plugin / relative
                self.assertTrue(copy.exists(), f"missing copy: {copy}")
                self.assertEqual(
                    hashlib.sha256(copy.read_bytes()).hexdigest(),
                    expected,
                    f"{copy} has drifted from {relative}",
                )


if __name__ == "__main__":
    unittest.main()

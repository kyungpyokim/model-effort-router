from pathlib import Path
import importlib.util
import json
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


if __name__ == "__main__":
    unittest.main()

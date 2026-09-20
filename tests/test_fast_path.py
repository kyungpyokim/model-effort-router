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
sys.path.insert(0, str(ROOT / "tests"))

import router  # noqa: E402

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

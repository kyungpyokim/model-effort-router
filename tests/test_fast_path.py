"""Tests for Fast Path workflow policies: Read-only Inspect and Trivial Edit Fast Path."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import router
from rules import is_read_only_inspect, is_trivial_edit_fast_path
CONFIG = router.load_config(ROOT / "config" / "model-map.json")


class FastPathTests(unittest.TestCase):
    def test_read_only_inspect_skips_plan_test_review(self):
        facts = {
            "mechanical_only": "no",
            "files_touched": "0",
            "requires_code_understanding": "no",
        }
        self.assertTrue(is_read_only_inspect("design", facts))
        self.assertTrue(is_read_only_inspect("review", facts))
        self.assertFalse(is_read_only_inspect("implementation", facts))

        # Under read_only_inspect, router produces no pipeline (no test, no review, no replan)
        result = router.route(
            "explain what this function does",
            "codex",
            CONFIG,
            classifier=lambda _: router.Classification(
                task_type="review",
                level="L1",
                risk_flags={f: False for f in router.RISK_FLAGS},
                reason="Inspection query",
                source="primary",
                facts=facts,
            ),
        )
        self.assertIsNone(result.pipeline)
        self.assertEqual(result.mode, "single")
        self.assertEqual(result.model, "gpt-5.6-luna")

    def test_trivial_edit_fast_path_qualifies_when_all_conditions_met(self):
        facts = {
            "mechanical_only": "yes",
            "files_touched": "1",
            "requires_code_understanding": "no",
            "crosses_module_boundary": "no",
            "crosses_service_boundary": "no",
            "needs_new_structure": "no",
            "changes_security_or_payment_logic": "no",
            "reviews_security_sensitive_code": "no",
            "security_domain": "none",
            "changes_public_api_contract": "no",
            "changes_persisted_data": "no",
            "irreversible_or_ledger_or_crypto": "no",
            "changes_trust_boundary": "no",
            "blast_radius": "narrow",
            "silent_failure_material_harm": "no",
        }
        self.assertTrue(is_trivial_edit_fast_path("implementation", "standard", facts))

        result = router.route(
            "fix typo in README",
            "codex",
            CONFIG,
            classifier=lambda _: router.Classification(
                task_type="implementation",
                level="L1",
                risk_flags={f: False for f in router.RISK_FLAGS},
                reason="Typo fix",
                source="primary",
                facts=facts,
            ),
        )
        self.assertIsNotNone(result.pipeline)
        self.assertIsNone(result.pipeline["review"])
        self.assertEqual(result.mode, "single")
        self.assertEqual(result.model, "gpt-5.6-luna")

    def test_trivial_edit_rejected_when_requires_code_understanding(self):
        facts = {
            "mechanical_only": "yes",
            "files_touched": "1",
            "requires_code_understanding": "yes",
            "security_domain": "none",
        }
        self.assertFalse(is_trivial_edit_fast_path("implementation", "standard", facts))

    def test_trivial_edit_rejected_on_elevated_risk_tier(self):
        facts = {
            "mechanical_only": "yes",
            "files_touched": "1",
            "requires_code_understanding": "no",
            "security_domain": "none",
        }
        self.assertFalse(is_trivial_edit_fast_path("implementation", "elevated", facts))

    def test_trivial_edit_rejected_on_security_sensitive_change(self):
        facts = {
            "mechanical_only": "yes",
            "files_touched": "1",
            "requires_code_understanding": "no",
            "changes_security_or_payment_logic": "yes",
            "security_domain": "auth",
        }
        self.assertFalse(is_trivial_edit_fast_path("implementation", "standard", facts))


if __name__ == "__main__":
    unittest.main()

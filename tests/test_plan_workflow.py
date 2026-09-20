"""Tests for Regular Workflow: Plan (Sol/Opus) -> Implement -> Test -> Review (Sol/Opus)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import router
CONFIG = router.load_config(ROOT / "config" / "model-map.json")


class PlanWorkflowTests(unittest.TestCase):
    def test_regular_workflow_includes_sol_review_at_level_4(self):
        result = router.route(
            "refactor authentication middleware",
            "codex",
            CONFIG,
            classifier=lambda _: router.Classification(
                task_type="implementation",
                level="L4",
                risk_flags={f: False for f in router.RISK_FLAGS},
                reason="L4 regular implementation",
                source="primary",
            ),
        )
        self.assertIsNotNone(result.pipeline)
        review = result.pipeline["review"]
        self.assertIsNotNone(review)
        self.assertEqual(review["model"], "gpt-5.6-sol")
        self.assertEqual(review["effort"], "high")

    def test_risk_escalation_raises_review_effort_to_xhigh(self):
        result = router.route(
            "update payment processor token handling",
            "codex",
            CONFIG,
            classifier=lambda _: router.Classification(
                task_type="implementation",
                level="L4",
                risk_flags={
                    f: (f == "security_sensitive" or f == "payment")
                    for f in router.RISK_FLAGS
                },
                risk_tier="elevated",
                reason="Payment logic change",
                source="primary",
            ),
        )
        self.assertIsNotNone(result.pipeline)
        review = result.pipeline["review"]
        self.assertIsNotNone(review)
        self.assertEqual(review["model"], "gpt-5.6-sol")
        self.assertEqual(review["effort"], "xhigh")

    def test_critical_risk_raises_review_effort_to_max(self):
        result = router.route(
            "irreversible ledger database migration",
            "codex",
            CONFIG,
            critical=True,
            classifier=lambda _: router.Classification(
                task_type="implementation",
                level="L5",
                risk_flags={
                    f: (f == "data_migration" or f == "security_sensitive")
                    for f in router.RISK_FLAGS
                },
                risk_tier="critical",
                reason="Irreversible ledger migration",
                source="primary",
            ),
        )
        self.assertIsNotNone(result.pipeline)
        review = result.pipeline["review"]
        self.assertIsNotNone(review)
        self.assertEqual(review["model"], "gpt-5.6-sol")
        self.assertEqual(review["effort"], "max")

    def test_claude_regular_workflow_assigns_opus_review(self):
        result = router.route(
            "refactor core parsing logic across modules",
            "claude-code",
            CONFIG,
            classifier=lambda _: router.Classification(
                task_type="implementation",
                level="L4",
                risk_flags={f: False for f in router.RISK_FLAGS},
                reason="L4 Claude implementation",
                source="primary",
            ),
        )
        self.assertIsNotNone(result.pipeline)
        review = result.pipeline["review"]
        self.assertIsNotNone(review)
        self.assertEqual(review["model"], "claude-opus-5")
        self.assertEqual(review["effort"], "high")


if __name__ == "__main__":
    unittest.main()

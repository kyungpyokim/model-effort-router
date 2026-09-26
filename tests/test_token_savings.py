from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("eval_token_savings", ROOT / "scripts" / "eval_token_savings.py")
token_savings = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = token_savings
SPEC.loader.exec_module(token_savings)


class TokenSavingsTests(unittest.TestCase):
    def test_extract_usage_from_codex_json_event_stream(self):
        events = "\n".join((
            json.dumps({"type": "item.completed", "item": {"type": "agent_message"}}),
            json.dumps({"type": "turn.completed", "usage": {
                "input_tokens": 120, "cached_input_tokens": 30,
                "output_tokens": 40, "reasoning_output_tokens": 25, "total_tokens": 160,
            }}),
        ))

        self.assertEqual(token_savings.parse_usage(events), {
            "input_tokens": 120, "cached_input_tokens": 30,
            "output_tokens": 40, "reasoning_output_tokens": 25, "total_tokens": 160,
        })

    def test_usage_fallback_does_not_double_count_reasoning_tokens(self):
        event = json.dumps({"type": "turn.completed", "usage": {
            "input_tokens": 120, "output_tokens": 40, "reasoning_output_tokens": 25,
        }})

        self.assertEqual(token_savings.parse_usage(event)["total_tokens"], 160)

    def test_executor_profile_uses_last_stage_of_multistage_route(self):
        self.assertEqual(token_savings.executor_profile({
            "mode": "two_stage",
            "stages": [("planner-model", "high"), ("executor-model", "medium")],
        }), ("executor-model", "medium"))

    def test_inspect_baseline_respects_its_l2_ceiling(self):
        row = next(row for row in token_savings.corpus_rows() if row["name"] == "L1_inspect_git_clean_status")

        self.assertEqual(row["baseline_level"], "L2")

    def test_summary_compares_successful_case_pairs_and_uses_total_tokens(self):
        cases = [
            {"name": "a", "expected_level": "L1", "routed": {"ok": True, "input_tokens": 80, "output_tokens": 20, "total_tokens": 100},
             "baseline": {"ok": True, "input_tokens": 100, "output_tokens": 100, "total_tokens": 200}},
            {"name": "b", "expected_level": "L2", "routed": {"ok": True, "input_tokens": 50, "output_tokens": 50, "total_tokens": 100},
             "baseline": {"ok": False, "input_tokens": None, "output_tokens": None}},
        ]

        summary = token_savings.summarize(cases)

        self.assertEqual(summary["paired_cases"], 1)
        self.assertEqual(summary["routed_total_tokens"], 100)
        self.assertEqual(summary["baseline_total_tokens"], 200)
        self.assertEqual(summary["token_savings_pct"], 50.0)

    def test_live_codex_call_reports_codex_usage(self):
        completed = mock.Mock(returncode=0, stdout=json.dumps({"type": "turn.completed", "usage": {
            "input_tokens": 10, "cached_input_tokens": 2, "output_tokens": 3,
            "reasoning_output_tokens": 1,
        }}), stderr="")
        with mock.patch.object(token_savings.subprocess, "run", return_value=completed):
            measured = token_savings.run_live_codex_call("gpt-6-luna", "low", "prompt")

        self.assertTrue(measured["ok"])
        self.assertEqual(measured["input_tokens"], 10)
        self.assertEqual(measured["reasoning_output_tokens"], 1)
        self.assertEqual(measured["total_tokens"], 13)


if __name__ == "__main__":
    unittest.main()

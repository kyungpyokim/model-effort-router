from __future__ import annotations

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
import e2e_usage  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "e2e_usage"

COMPLETE_USAGE = {
    "input_tokens": 1500,
    "cached_input_tokens": 1200,
    "cache_write_tokens": 300,
    "output_tokens": 400,
    "reasoning_tokens": 160,
    "total_tokens": 1900,
}

RECORD_KEYS = {
    "run_id", "case_id", "mode", "stage", "attempt", "model", "effort",
    "input_tokens", "cached_input_tokens", "cache_write_tokens",
    "output_tokens", "reasoning_tokens", "total_tokens", "usage_status",
    "exit_code", "wall_time_ms",
}


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def sample_context() -> e2e_usage.UsageContext:
    return e2e_usage.UsageContext(
        run_id="synthetic-run-0001",
        case_id="synthetic_case",
        mode="routed",
        stage="implementer",
        attempt=1,
        model="gpt-6-luna",
        effort="high",
    )


def validated_codex_argv(access: str) -> list[str]:
    """A representative validated Codex argv from the commands.py contract."""
    argv = commands.stage_command(
        "codex",
        {"model": "gpt-6-luna", "effort": "high"},
        "Synthetic developer instructions for the argv invariant test.",
        "IMPLEMENT\nSynthetic argv contract task.",
        access,
    )
    commands.validate_argv("codex", list(argv), model="gpt-6-luna", effort="high", access=access)
    return argv


class InstrumentArgvTests(unittest.TestCase):
    def test_instrument_adds_only_the_json_flag_at_the_exec_position(self):
        for access in ("read", "edit"):
            with self.subTest(access=access):
                validated = validated_codex_argv(access)
                instrumented = e2e_usage.instrument_execution_argv("codex", validated)

                self.assertEqual(
                    instrumented,
                    [validated[0], validated[1], "--json", *validated[2:]],
                )
                self.assertEqual(len(instrumented), len(validated) + 1)

    def test_strip_is_the_exact_inverse_of_instrument(self):
        for access in ("read", "edit"):
            with self.subTest(access=access):
                validated = validated_codex_argv(access)

                execution = e2e_usage.instrument_execution_argv("codex", validated)

                self.assertEqual(
                    e2e_usage.strip_instrumentation("codex", execution),
                    validated,
                )

    def test_env_values_never_reach_the_model_argv(self):
        env = {
            "MODEL_EFFORT_ROUTER_INSTRUMENT_USAGE": "1",
            "MODEL_EFFORT_ROUTER_USAGE_JSONL": "/tmp/synthetic-usage-sink.jsonl",
        }
        with mock.patch.dict(os.environ, env):
            instrumented = e2e_usage.instrument_execution_argv(
                "codex", validated_codex_argv("read")
            )

        for value in env.values():
            self.assertNotIn(value, instrumented)
        self.assertEqual(instrumented.count("--json"), 1)

    def test_instrument_refuses_an_already_instrumented_argv(self):
        validated = validated_codex_argv("read")
        instrumented = e2e_usage.instrument_execution_argv("codex", validated)

        with self.assertRaises(ValueError):
            e2e_usage.instrument_execution_argv("codex", instrumented)

    def test_instrument_refuses_the_interactive_codex_form(self):
        with self.assertRaises(ValueError):
            e2e_usage.instrument_execution_argv(
                "codex", ["codex", "--sandbox", "workspace-write", "prompt"]
            )

    def test_unsupported_providers_are_refused_not_silently_changed(self):
        claude_argv = ["claude", "-p", "--model", "opus", "--", "task"]

        with self.assertRaises(ValueError):
            e2e_usage.instrument_execution_argv("claude-code", claude_argv)
        with self.assertRaises(ValueError):
            e2e_usage.strip_instrumentation("claude-code", claude_argv)


class CodexJsonlParserTests(unittest.TestCase):
    def parse(self, name: str, *, exit_code: int = 0, wall_time_ms: int = 1200):
        return e2e_usage.parse_codex_jsonl(
            fixture_text(name), sample_context(),
            exit_code=exit_code, wall_time_ms=wall_time_ms,
        )

    def test_complete_usage_fixture_parses_as_complete(self):
        parsed = self.parse("codex_complete.jsonl")

        self.assertEqual(parsed.usage.usage_status, "complete")
        self.assertEqual(
            {
                "input_tokens": parsed.usage.input_tokens,
                "cached_input_tokens": parsed.usage.cached_input_tokens,
                "cache_write_tokens": parsed.usage.cache_write_tokens,
                "output_tokens": parsed.usage.output_tokens,
                "reasoning_tokens": parsed.usage.reasoning_tokens,
                "total_tokens": parsed.usage.total_tokens,
            },
            COMPLETE_USAGE,
        )
        self.assertIsInstance(parsed.raw_events, tuple)
        self.assertTrue(parsed.raw_events)
        self.assertTrue(all(isinstance(event, dict) for event in parsed.raw_events))
        self.assertEqual(parsed.exit_code, 0)
        self.assertEqual(parsed.wall_time_ms, 1200)

    def test_cached_input_is_a_subset_of_input_and_not_added_to_total(self):
        usage = self.parse("codex_complete.jsonl").usage

        self.assertLess(usage.cached_input_tokens, usage.input_tokens)
        self.assertLessEqual(usage.cache_write_tokens, usage.input_tokens)
        self.assertEqual(usage.total_tokens, usage.input_tokens + usage.output_tokens)
        self.assertNotEqual(
            usage.total_tokens,
            usage.input_tokens + usage.cached_input_tokens + usage.cache_write_tokens,
        )

    def test_reasoning_tokens_are_a_subset_of_output_and_not_added_to_total(self):
        usage = self.parse("codex_complete.jsonl").usage

        self.assertLess(usage.reasoning_tokens, usage.output_tokens)
        self.assertEqual(usage.total_tokens, usage.input_tokens + usage.output_tokens)
        self.assertNotEqual(
            usage.total_tokens, usage.output_tokens + usage.reasoning_tokens
        )

    def test_total_never_double_counts_any_provider_subfield(self):
        usage = self.parse("codex_complete.jsonl").usage

        self.assertEqual(usage.total_tokens, 1900)
        self.assertNotEqual(
            usage.total_tokens,
            usage.input_tokens
            + usage.cached_input_tokens
            + usage.cache_write_tokens
            + usage.output_tokens
            + usage.reasoning_tokens,
        )

    def test_final_logical_output_is_the_last_completed_agent_message(self):
        parsed = self.parse("codex_complete.jsonl")

        self.assertEqual(
            parsed.logical_output,
            "SYNTHETIC FIXTURE: implementation complete; all synthetic checks pass.",
        )

    def test_malformed_and_unrelated_events_are_tolerated(self):
        parsed = self.parse("codex_malformed.jsonl")

        # Non-JSON chatter, a truncated JSON line, and a JSON array line are skipped;
        # only the four valid event objects survive.
        self.assertEqual(len(parsed.raw_events), 4)
        self.assertTrue(all(isinstance(event, dict) for event in parsed.raw_events))
        self.assertEqual(parsed.usage.usage_status, "missing")
        self.assertEqual(
            parsed.logical_output,
            "SYNTHETIC FIXTURE: logical output survives malformed stream noise.",
        )

    def test_partial_usage_is_never_promoted_to_complete(self):
        usage = self.parse("codex_partial.jsonl").usage

        self.assertEqual(usage.usage_status, "partial")
        self.assertEqual(usage.input_tokens, 900)
        self.assertEqual(usage.cached_input_tokens, 700)
        self.assertEqual(usage.output_tokens, 0)
        self.assertEqual(usage.total_tokens, 900)
        self.assertNotEqual(
            usage.total_tokens, usage.input_tokens + usage.cached_input_tokens
        )
        self.assertEqual(
            self.parse("codex_partial.jsonl").logical_output,
            "SYNTHETIC FIXTURE: partial turn output recorded before interruption.",
        )

    def test_missing_usage_is_reported_as_missing_not_as_zero(self):
        parsed = e2e_usage.parse_codex_jsonl(
            "", sample_context(), exit_code=0, wall_time_ms=5
        )
        usage = parsed.usage

        self.assertEqual(usage.usage_status, "missing")
        self.assertEqual(
            (usage.input_tokens, usage.output_tokens, usage.total_tokens), (0, 0, 0)
        )
        self.assertEqual(parsed.logical_output, "")

    def test_nonzero_exit_with_recoverable_usage_still_parses(self):
        parsed = self.parse("codex_complete.jsonl", exit_code=137, wall_time_ms=4242)

        self.assertEqual(parsed.usage.usage_status, "complete")
        self.assertEqual(parsed.usage.total_tokens, 1900)
        self.assertEqual(parsed.exit_code, 137)
        self.assertEqual(parsed.wall_time_ms, 4242)


class UsageJsonlRecorderTests(unittest.TestCase):
    def test_append_writes_one_normalized_record_per_invocation(self):
        parsed = e2e_usage.parse_codex_jsonl(
            fixture_text("codex_complete.jsonl"), sample_context(),
            exit_code=3, wall_time_ms=999,
        )
        with tempfile.TemporaryDirectory() as tmp:
            sink = Path(tmp) / "usage.jsonl"
            e2e_usage.append_usage_jsonl(sink, sample_context(), parsed)
            e2e_usage.append_usage_jsonl(sink, sample_context(), parsed)

            lines = sink.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(lines), 2)
        record = json.loads(lines[0])
        self.assertEqual(set(record), RECORD_KEYS)
        self.assertEqual(record["run_id"], "synthetic-run-0001")
        self.assertEqual(record["case_id"], "synthetic_case")
        self.assertEqual(record["mode"], "routed")
        self.assertEqual(record["stage"], "implementer")
        self.assertEqual(record["attempt"], 1)
        self.assertEqual(record["model"], "gpt-6-luna")
        self.assertEqual(record["effort"], "high")
        self.assertEqual(record["usage_status"], "complete")
        self.assertEqual(record["total_tokens"], 1900)
        self.assertEqual(record["exit_code"], 3)
        self.assertEqual(record["wall_time_ms"], 999)

    def test_append_keeps_missing_usage_explicit(self):
        parsed = e2e_usage.parse_codex_jsonl(
            "", sample_context(), exit_code=0, wall_time_ms=5
        )
        with tempfile.TemporaryDirectory() as tmp:
            sink = Path(tmp) / "usage.jsonl"
            e2e_usage.append_usage_jsonl(sink, sample_context(), parsed)

            record = json.loads(sink.read_text(encoding="utf-8").strip())

        self.assertEqual(record["usage_status"], "missing")
        self.assertEqual(record["total_tokens"], 0)


if __name__ == "__main__":
    unittest.main()

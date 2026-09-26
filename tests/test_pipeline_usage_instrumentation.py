"""Usage-instrumentation wiring in the real pipeline execution seam.

Instrumentation OFF must be the exact legacy path: validated argv unchanged, byte-identical
stdout, same exit code, stderr still inherited by the child. Instrumentation ON (both approved
env vars) must execute validated argv + only the trusted ``--json`` flag, hand downstream stages
exactly the reconstructed logical output, and append one usage record per model call. Env values
never become model argv.
"""
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

import e2e_usage  # noqa: E402
import pipeline  # noqa: E402
import router  # noqa: E402

# The harness-owned run-context channel (spec 3.6 / Task 8): recorder metadata only.
RUN_CONTEXT_ENV = "MODEL_EFFORT_ROUTER_RUN_CONTEXT"
RUN_CONTEXT = {"run_id": "run-e2e-001", "case_id": "case-07", "mode": "routed"}

PLAN = {
    "schema_version": 1,
    "analysis": {"current_structure": [], "constraints": [], "affected_areas": [], "risks": []},
    "implementation_plan": {"steps": [], "expected_files": [], "compatibility_requirements": []},
    "validation": {"commands": [], "acceptance_criteria": [], "rollback_notes": []},
}
PLAN_JSON = json.dumps(PLAN)
REVIEW_REPLY = "no findings\nVERDICT: PASS"
GREEN_REPLIES = [{"out": PLAN_JSON}, {"out": ""}, {"out": REVIEW_REPLY}]
GREEN_ROLES = ["plan", "execute", "review"]

# Deterministic fake codex: records argv, then answers either the legacy way (plain text) or,
# only when it sees --json, as Codex structured JSONL with fixed usage numbers.
FAKE_CODEX = """#!{python}
import json, os, pathlib, sys
argv = sys.argv[1:]
text = " ".join(argv)
role = next((name for marker, name in (
    ("merged verification", "review"), ("fix stage", "fix"),
    ("planning stage", "plan"),
) if marker in text), "execute")
directory = pathlib.Path(os.environ["FAKE_DIR"])
index = int((directory / "count").read_text()) if (directory / "count").exists() else 0
(directory / "count").write_text(str(index + 1))
with (directory / "calls.jsonl").open("a") as stream:
    stream.write(json.dumps({{"role": role, "argv": argv, "prompt": argv[-1], "text": text}}) + chr(10))
replies = json.loads((directory / "replies.json").read_text())
reply = replies[index] if index < len(replies) else {{}}
if reply.get("stderr"):
    sys.stderr.write(reply["stderr"])
out = reply.get("out", "")
if "--json" in argv:
    print(json.dumps({{"type": "turn.completed", "usage": {{"input_tokens": 120, "cached_input_tokens": 20, "cache_write_tokens": 0, "output_tokens": 60, "reasoning_tokens": 10}}}}))
    print(json.dumps({{"type": "item.completed", "item": {{"type": "agent_message", "text": out}}}}))
else:
    print(out)
sys.exit(reply.get("rc", 0))
"""


@contextlib.contextmanager
def telemetry(updates: dict | None = None):
    """Run with an explicit telemetry env; every approved var not named in ``updates`` is absent."""
    with mock.patch.dict(os.environ, updates or {}, clear=False):
        for name in (e2e_usage.INSTRUMENT_USAGE_ENV, e2e_usage.USAGE_JSONL_ENV, RUN_CONTEXT_ENV):
            if not updates or name not in updates:
                os.environ.pop(name, None)
        yield


class PipelineUsageCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        fake = self.dir / "codex"
        fake.write_text(FAKE_CODEX.format(python=sys.executable), encoding="utf-8")
        fake.chmod(0o755)
        self.work = self.dir / "work"
        self.work.mkdir()
        self.sink = self.dir / "usage.jsonl"
        old_path, old_fake = os.environ.get("PATH"), os.environ.get("FAKE_DIR")
        os.environ["PATH"] = f"{self.dir}{os.pathsep}{old_path}"
        os.environ["FAKE_DIR"] = str(self.dir)
        self.addCleanup(os.environ.__setitem__, "PATH", old_path)
        self.addCleanup(lambda: os.environ.pop("FAKE_DIR") if old_fake is None else os.environ.__setitem__("FAKE_DIR", old_fake))

    def payload(self, level="L4", task_type="implementation"):
        config = router.load_config(ROOT / "config" / "model-map.json")
        result = router.route("do the thing", "codex", config, level, task_type)
        return router.result_payload(result, router.stage_commands(result, "do the thing"), "do the thing")

    def run_route(self, replies, env, payload=None, tests=("true",)):
        """One pipeline run with fresh fake-codex state; returns (rc, calls, stdout, stderr, payload)."""
        payload = payload or self.payload()
        for name in ("count", "calls.jsonl"):
            (self.dir / name).unlink(missing_ok=True)
        (self.dir / "replies.json").write_text(json.dumps(replies), encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with telemetry(env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = pipeline.run_route(payload, list(tests), str(self.work))
        path = self.dir / "calls.jsonl"
        calls = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
        return rc, calls, out.getvalue(), err.getvalue(), payload

    def on_env(self, payload=None):
        return {
            e2e_usage.INSTRUMENT_USAGE_ENV: "1",
            e2e_usage.USAGE_JSONL_ENV: str(self.sink),
            RUN_CONTEXT_ENV: json.dumps(RUN_CONTEXT),
        }

    def records(self):
        return [json.loads(line) for line in self.sink.read_text(encoding="utf-8").splitlines()]

    @staticmethod
    def full_argv(call):
        return ["codex", *call["argv"]]


class InstrumentationOffTests(PipelineUsageCase):
    """Step 2: env-disabled execution is the exact legacy path."""

    def test_off_sends_the_exact_validated_argv(self):
        rc, calls, _, _, payload = self.run_route(GREEN_REPLIES, {})
        self.assertEqual(rc, 0)
        self.assertEqual([call["role"] for call in calls], GREEN_ROLES)
        self.assertEqual(self.full_argv(calls[0]), payload["steps"][0]["command"])
        self.assertEqual(self.full_argv(calls[1]), payload["steps"][-1]["command"])
        for call in calls:
            self.assertNotIn("--json", call["argv"])

    def test_off_stdout_is_the_exact_legacy_bytes(self):
        rc, _, out, _, _ = self.run_route(GREEN_REPLIES, {})
        self.assertEqual(rc, 0)
        expected = "".join(f"{reply.get('out', '')}\n" for reply in GREEN_REPLIES)
        self.assertEqual(out, expected)
        # The planned output downstream consumed is byte-identical to what the model printed.
        self.assertIn(PLAN_JSON + "\n", out)

    def test_off_propagates_the_stage_exit_code(self):
        rc, calls, _, _, _ = self.run_route([{"out": PLAN_JSON}, {"rc": 7}], {})
        self.assertEqual(rc, 7)
        self.assertEqual([call["role"] for call in calls], GREEN_ROLES[:2])

    def test_off_keeps_child_stderr_on_the_process_stderr(self):
        # Route fd 2 through a pipe: run_capture captures stdout only, so the stage's stderr
        # must still reach the process stderr, not the captured stdout stream.
        payload = self.payload()
        saved = os.dup(2)
        read_fd, write_fd = os.pipe()
        try:
            os.dup2(write_fd, 2)
            rc, _, out, _, _ = self.run_route([{"rc": 9, "stderr": "stage-stderr-marker\n", "out": ""}], {}, payload=payload)
        finally:
            os.dup2(saved, 2)
            os.close(saved)
            os.close(write_fd)
        captured = os.read(read_fd, 65536).decode("utf-8", "replace")
        os.close(read_fd)
        self.assertEqual(rc, 9)
        self.assertIn("stage-stderr-marker", captured)
        self.assertNotIn("stage-stderr-marker", out)

    def test_off_writes_no_usage_sink_even_when_it_is_configured(self):
        rc, calls, _, _, _ = self.run_route(GREEN_REPLIES, {e2e_usage.USAGE_JSONL_ENV: str(self.sink)})
        self.assertEqual(rc, 0)
        self.assertFalse(self.sink.exists())
        self.assertNotIn("--json", calls[0]["argv"])

    def test_enable_without_a_sink_keeps_legacy_execution(self):
        # Instrumentation requires the complete env contract: enable without a sink never
        # changes the command (a half-configured run cannot silently drop records either),
        # and the misconfiguration is announced instead of passing unnoticed.
        rc, calls, _, err, _ = self.run_route(GREEN_REPLIES, {e2e_usage.INSTRUMENT_USAGE_ENV: "1"})
        self.assertEqual(rc, 0)
        self.assertNotIn("--json", calls[0]["argv"])
        self.assertFalse(self.sink.exists())
        self.assertIn("usage instrumentation enabled but", err)

    def test_on_an_uninstrumentable_codex_argv_keeps_the_legacy_execution(self):
        # The fail-closed argv precondition warns and runs legacy rather than crashing a
        # validated route, matching the non-codex provider branch above it.
        (self.dir / "replies.json").write_text(json.dumps([{"out": "legacy ok"}]), encoding="utf-8")
        (self.dir / "count").unlink(missing_ok=True)
        err = io.StringIO()
        with telemetry(self.on_env()), contextlib.redirect_stderr(err):
            rc, output = pipeline.instrumented_run_capture(
                ["codex", "exec", "prompt"], str(self.work), stage="planner"
            )
        path = self.dir / "calls.jsonl"
        calls = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
        self.assertEqual(rc, 0)
        self.assertEqual(output, "legacy ok\n")
        self.assertEqual(len(calls), 1)
        self.assertNotIn("--json", calls[0]["argv"])
        self.assertFalse(self.sink.exists())
        self.assertIn("running uninstrumented", err.getvalue())


class InstrumentationOnTests(PipelineUsageCase):
    """Steps 3: mocked Codex JSONL through the real pipeline seam."""

    def run_green_pair(self):
        """The same payload and provider answers once off, once on, for byte-level comparison."""
        payload = self.payload()
        off = self.run_route(GREEN_REPLIES, {}, payload=payload)
        plan_path = Path(payload["steps"][0]["output"]["path"])
        off_plan = plan_path.read_text(encoding="utf-8")
        on = self.run_route(GREEN_REPLIES, self.on_env(), payload=payload)
        on_plan = plan_path.read_text(encoding="utf-8")
        return off, on, off_plan, on_plan

    def test_on_sends_validated_argv_plus_only_the_json_flag(self):
        (off_rc, off_calls, _, _, _), (on_rc, on_calls, _, _, _), _, _ = self.run_green_pair()
        self.assertEqual((off_rc, on_rc), (0, 0))
        self.assertEqual(len(off_calls), len(on_calls))
        for off_call, on_call in zip(off_calls, on_calls):
            off_full, on_full = self.full_argv(off_call), self.full_argv(on_call)
            self.assertEqual(on_full, off_full[:2] + ["--json"] + off_full[2:])
            self.assertEqual(e2e_usage.strip_instrumentation("codex", on_full), off_full)
            self.assertEqual(on_full[2], e2e_usage.CODEX_JSON_FLAG)

    def test_on_downstream_receives_only_the_reconstructed_logical_output(self):
        (off_rc, off_calls, _, _, _), (on_rc, on_calls, _, _, _), off_plan, on_plan = self.run_green_pair()
        self.assertEqual((off_rc, on_rc), (0, 0))
        # The plan artifact is byte-identical with and without instrumentation...
        self.assertEqual(off_plan, PLAN_JSON)
        self.assertEqual(on_plan, PLAN_JSON)
        # ...and every downstream prompt (review included) is byte-identical too: only the
        # trusted flag differs between the two executions.
        self.assertEqual(
            [call["prompt"] for call in on_calls],
            [call["prompt"] for call in off_calls],
        )
        # Raw structured events never reach a model prompt.
        for call in on_calls:
            for marker in ("item.completed", "agent_message", '"usage"'):
                self.assertNotIn(marker, call["prompt"])

    def test_on_appends_one_usage_record_per_model_call(self):
        rc, _, _, _, payload = self.run_route(GREEN_REPLIES, self.on_env())
        self.assertEqual(rc, 0)
        records = self.records()
        self.assertEqual(len(records), 3)
        review = payload["pipeline"]["review"]
        self.assertEqual([record["stage"] for record in records], ["planner", "executor", "reviewer"])
        self.assertEqual([record["attempt"] for record in records], [0, 0, 1])
        self.assertEqual(
            [record["model"] for record in records],
            [payload["steps"][0]["model"], payload["steps"][-1]["model"], review["model"]],
        )
        self.assertEqual(
            [record["effort"] for record in records],
            [payload["steps"][0].get("effort"), payload["steps"][-1].get("effort"), review.get("effort")],
        )
        for record in records:
            self.assertEqual(
                {key: record[key] for key in ("run_id", "case_id", "mode")}, RUN_CONTEXT
            )
            self.assertEqual(record["provider"], "openai")
            self.assertEqual(
                (record["input_tokens"], record["cached_input_tokens"], record["cache_write_tokens"],
                 record["output_tokens"], record["reasoning_tokens"], record["total_tokens"]),
                (120, 20, 0, 60, 10, 180),
            )
            self.assertEqual(record["usage_status"], "complete")
            self.assertEqual(record["exit_code"], 0)
            self.assertIsInstance(record["wall_time_ms"], int)
            self.assertGreaterEqual(record["wall_time_ms"], 0)

    def test_on_keeps_environment_values_out_of_model_argv(self):
        rc, calls, _, _, _ = self.run_route(GREEN_REPLIES, self.on_env())
        self.assertEqual(rc, 0)
        joined = " ".join(call["text"] for call in calls)
        self.assertNotIn(str(self.sink), joined)
        self.assertNotIn(json.dumps(RUN_CONTEXT), joined)
        self.assertNotIn("MODEL_EFFORT_ROUTER", joined)


if __name__ == "__main__":
    unittest.main()

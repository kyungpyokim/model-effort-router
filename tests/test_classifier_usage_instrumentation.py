"""Usage-instrumentation wiring in the real Routed classifier/fallback path.

The classifier spawns its own ``codex exec`` subprocess (it never flows through
``pipeline.run_capture``), so this file pins the seam around that call: OFF keeps the exact
legacy argv and writes nothing; ON (both approved env vars) executes validated argv + only the
trusted ``--json`` flag, parses the answer back to the logical reply, and records every model
invocation — including the retry and the fallback attempts — as ``stage="classifier"``.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import e2e_usage  # noqa: E402
import jev_provider  # noqa: E402
import router  # noqa: E402

RUN_CONTEXT_ENV = "MODEL_EFFORT_ROUTER_RUN_CONTEXT"
RUN_CONTEXT = {"run_id": "run-e2e-001", "case_id": "case-07", "mode": "routed"}
CONFIG = router.load_config(ROOT / "config" / "model-map.json")

# A fully settled classification: every fact known, so the router spends exactly one
# classifier model call (no bounded lookup).
FACTS = {
    "mechanical_only": "no",
    "files_touched": "1",
    "crosses_module_boundary": "no",
    "crosses_service_boundary": "no",
    "fix_or_result_known": "yes",
    "intermittent_or_concurrency": "no",
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
    "requires_code_understanding": "no",
}
CLASSIFICATION_JSON = json.dumps({
    "task_type": "implementation",
    "facts": FACTS,
    "delegability": 1,
    "evidence": [],
    "reason": "Clear scoped change.",
})

# Deterministic fake codex classifier: records argv; mode "ok" answers with the valid reply,
# "fail" exits non-zero without output, "garbage" answers with an unparseable reply. Only the
# --json form speaks Codex structured JSONL, with fixed usage numbers.
FAKE_CODEX = """#!{python}
import json, os, pathlib, sys
argv = sys.argv[1:]
directory = pathlib.Path(os.environ["FAKE_CLASSIFIER_DIR"])
with (directory / "calls.jsonl").open("a") as stream:
    stream.write(json.dumps({{"argv": argv}}) + chr(10))
mode = (directory / "mode").read_text().strip()
if mode == "fail":
    sys.exit(1)
text = (directory / "reply.json").read_text() if mode == "ok" else "not a json reply"
if "--json" in argv:
    print(json.dumps({{"type": "turn.completed", "usage": {{"input_tokens": 90, "cached_input_tokens": 0, "cache_write_tokens": 0, "output_tokens": 30, "reasoning_tokens": 5}}}}))
    print(json.dumps({{"type": "item.completed", "item": {{"type": "agent_message", "text": text}}}}))
else:
    print(text)
sys.exit(0)
"""


@contextlib.contextmanager
def telemetry(updates: dict | None = None):
    """Explicit telemetry env + Jev preflight pinned off, so classification is the real CLI path."""
    base = {jev_provider.JEV_STAGE_ENV: "off"}
    base.update(updates or {})
    with mock.patch.dict(os.environ, base, clear=False):
        for name in (e2e_usage.INSTRUMENT_USAGE_ENV, e2e_usage.USAGE_JSONL_ENV, RUN_CONTEXT_ENV):
            if not updates or name not in updates:
                os.environ.pop(name, None)
        yield


class ClassifierUsageCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        fake = self.dir / "codex"
        fake.write_text(FAKE_CODEX.format(python=sys.executable), encoding="utf-8")
        fake.chmod(0o755)
        (self.dir / "mode").write_text("ok", encoding="utf-8")
        (self.dir / "reply.json").write_text(CLASSIFICATION_JSON, encoding="utf-8")
        self.sink = self.dir / "usage.jsonl"
        old_path, old_dir = os.environ.get("PATH"), os.environ.get("FAKE_CLASSIFIER_DIR")
        os.environ["PATH"] = f"{self.dir}{os.pathsep}{old_path}"
        os.environ["FAKE_CLASSIFIER_DIR"] = str(self.dir)
        self.addCleanup(os.environ.__setitem__, "PATH", old_path)
        self.addCleanup(
            lambda: os.environ.pop("FAKE_CLASSIFIER_DIR") if old_dir is None
            else os.environ.__setitem__("FAKE_CLASSIFIER_DIR", old_dir)
        )

    def classify(self, env, mode="ok"):
        """The real Routed entry: router.route() with no injected classifier spawns the CLI."""
        (self.dir / "calls.jsonl").unlink(missing_ok=True)
        (self.dir / "mode").write_text(mode, encoding="utf-8")
        with telemetry(env):
            result = router.route("do the thing", "codex", CONFIG)
        path = self.dir / "calls.jsonl"
        calls = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
        return result, calls

    def on_env(self):
        return {
            e2e_usage.INSTRUMENT_USAGE_ENV: "1",
            e2e_usage.USAGE_JSONL_ENV: str(self.sink),
            RUN_CONTEXT_ENV: json.dumps(RUN_CONTEXT),
        }

    def classify_raising(self, exc):
        """The real Routed entry while the classifier's own ``subprocess.run`` fails as ``exc``.

        The seam must record the invocation even though no process ever exits: a timeout or a
        spawn failure still burned a model call, and Review Focus #1 requires every call in the
        sink rather than a silent undercount.
        """
        (self.dir / "calls.jsonl").unlink(missing_ok=True)
        real_run = subprocess.run

        def explode(cmd, **kwargs):
            if "--output-schema" in cmd:
                raise exc
            return real_run(cmd, **kwargs)

        with telemetry(self.on_env()), mock.patch("subprocess.run", side_effect=explode):
            return router.route("do the thing", "codex", CONFIG)

    def records(self):
        return [json.loads(line) for line in self.sink.read_text(encoding="utf-8").splitlines()]

    @staticmethod
    def full_argv(call):
        return ["codex", *call["argv"]]


class ClassifierInstrumentationOffTests(ClassifierUsageCase):
    def test_off_keeps_the_legacy_classifier_argv_and_writes_nothing(self):
        result, calls = self.classify({e2e_usage.USAGE_JSONL_ENV: str(self.sink)})
        self.assertEqual((result.level, result.source), ("L2", "gpt-6-luna"))
        self.assertEqual(len(calls), 1)
        argv = self.full_argv(calls[0])
        self.assertEqual(argv[:3], ["codex", "exec", "--ephemeral"])
        self.assertNotIn("--json", argv)
        self.assertFalse(self.sink.exists())


class ClassifierInstrumentationOnTests(ClassifierUsageCase):
    def test_on_instruments_the_classifier_seam_and_records_one_usage_record(self):
        result, calls = self.classify(self.on_env())
        self.assertEqual((result.level, result.source), ("L2", "gpt-6-luna"))
        self.assertEqual(len(calls), 1)
        argv = self.full_argv(calls[0])
        # validated argv + only the trusted structured-output flag, at the exec position
        self.assertEqual(argv[:3], ["codex", "exec", "--json"])
        self.assertEqual(argv[3], "--ephemeral")
        self.assertEqual(e2e_usage.strip_instrumentation("codex", argv), ["codex", "exec", *argv[3:]])
        # neither env value may become model argv
        joined = " ".join(argv)
        self.assertNotIn(str(self.sink), joined)
        self.assertNotIn(json.dumps(RUN_CONTEXT), joined)
        self.assertNotIn("MODEL_EFFORT_ROUTER", joined)
        # one complete record with the classifier's stage/model/effort
        records = self.records()
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["stage"], "classifier")
        self.assertEqual(record["provider"], "openai")
        self.assertEqual(record["attempt"], 0)
        self.assertEqual(record["model"], "gpt-6-luna")
        self.assertEqual(record["effort"], "low")
        self.assertEqual({key: record[key] for key in ("run_id", "case_id", "mode")}, RUN_CONTEXT)
        self.assertEqual(
            (record["input_tokens"], record["cached_input_tokens"], record["output_tokens"],
             record["reasoning_tokens"], record["total_tokens"]),
            (90, 0, 30, 5, 120),
        )
        self.assertEqual(record["usage_status"], "complete")
        self.assertEqual(record["exit_code"], 0)

    def test_on_records_every_fallback_invocation(self):
        # "process failed" is retryable: the router spends two model calls and both are recorded,
        # with their missing usage kept explicit instead of zero-filled as a measurement.
        result, calls = self.classify(self.on_env(), mode="fail")
        self.assertEqual(result.source, "fallback")
        self.assertEqual(result.level, "L3")
        self.assertEqual(len(calls), 2)
        records = self.records()
        self.assertEqual(len(records), 2)
        for record in records:
            self.assertEqual(record["stage"], "classifier")
            self.assertEqual(record["model"], "gpt-6-luna")
            self.assertEqual(record["exit_code"], 1)
            self.assertEqual(record["usage_status"], "missing")
            self.assertEqual(record["total_tokens"], 0)
        self.assertEqual([record["attempt"] for record in records], [0, 0])

    def test_on_records_a_timed_out_invocation(self):
        # Timeout is not retryable (one invocation), but it still burned the call: the sink
        # must get exactly one record with the failure visible, never zero lines.
        result = self.classify_raising(subprocess.TimeoutExpired(["codex", "exec"], 0.5))
        self.assertEqual((result.source, result.level), ("fallback", "L3"))
        records = self.records()
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["stage"], "classifier")
        self.assertEqual(record["provider"], "openai")
        self.assertEqual(record["model"], "gpt-6-luna")
        self.assertEqual(record["effort"], "low")
        self.assertEqual({key: record[key] for key in ("run_id", "case_id", "mode")}, RUN_CONTEXT)
        self.assertEqual(record["usage_status"], "missing")
        self.assertEqual(record["total_tokens"], 0)
        self.assertEqual(record["exit_code"], 124)
        self.assertGreaterEqual(record["wall_time_ms"], 0)

    def test_on_records_a_spawn_failed_invocation(self):
        # Same contract for OSError: a process that never started still leaves one record in
        # the sink with a sentinel exit code, so the run's telemetry stays complete.
        result = self.classify_raising(OSError("No such file or directory"))
        self.assertEqual((result.source, result.level), ("fallback", "L3"))
        records = self.records()
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["stage"], "classifier")
        self.assertEqual(record["usage_status"], "missing")
        self.assertEqual(record["total_tokens"], 0)
        self.assertEqual(record["exit_code"], 12)
        self.assertGreaterEqual(record["wall_time_ms"], 0)

    def test_on_a_broken_sink_never_becomes_a_classification_failure(self):
        # A sink fault is a telemetry fault: it must not be relabelled as the schema-read
        # failure and cost the run its classification.
        broken = self.dir / "broken-sink"
        broken.mkdir()
        env = {**self.on_env(), e2e_usage.USAGE_JSONL_ENV: str(broken)}
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            result, calls = self.classify(env)
        self.assertEqual((result.level, result.source), ("L2", "gpt-6-luna"))
        self.assertEqual(len(calls), 1)
        self.assertIn("usage sink write failed", err.getvalue())

    def test_on_records_a_fallback_answered_with_invalid_output(self):
        # Unparseable output: one call, no retry, yet the usage the provider reported is kept.
        result, calls = self.classify(self.on_env(), mode="garbage")
        # The safe fallback (L3) with exactly one call proves the non-retryable invalid-output path.
        self.assertEqual((result.source, result.level), ("fallback", "L3"))
        self.assertEqual(len(calls), 1)
        records = self.records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["stage"], "classifier")
        self.assertEqual(records[0]["exit_code"], 0)
        self.assertEqual(records[0]["usage_status"], "complete")
        self.assertEqual(records[0]["total_tokens"], 120)


if __name__ == "__main__":
    unittest.main()

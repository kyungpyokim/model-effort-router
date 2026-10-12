import contextlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path

from model_effort_router.cli import main


def _log(sdir, name, *events):
    (Path(sdir) / f"{name}.log.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")


class ReportTest(unittest.TestCase):
    def report(self, sdir, *argv):
        out = io.StringIO()
        self.assertEqual(main(["report", *argv], env={"MER_STATE_DIR": sdir}, out=out), 0)
        return out.getvalue()

    def test_lists_model_effort_and_token_usage(self):
        with tempfile.TemporaryDirectory() as sdir:
            route = {
                "ts": 1,
                "event": "route",
                "target": "route",
                "advice": {"action": "spawn"},
                "classifier_usage": {"input_tokens": 1234, "cached_input_tokens": 0, "output_tokens": 56},
                "decision": {"role": "review", "backend": "jev", "model": "claude-opus-5-5", "applied_effort": "high"},
            }
            run = {
                "ts": 2,
                "event": "run",
                "role": "fix",
                "actual_model": "claude-sonnet-5-5",
                "applied_effort": "low",
                "status": "complete",
                "usage": {"input": 900, "cached_input": 100, "output": 40},
            }
            start = {
                "ts": 3,
                "event": "subagent_start",
                "agent_type": "model-effort-router:effort-high",
                "model": None,
                "correlation": None,
            }
            _log(sdir, "aaaaaaaa-1", route, run, start, {"ts": 4, "event": "route", "target": "no_route"})
            _log(sdir, "bbbbbbbb-2", {**route, "ts": 5})
            text = self.report(sdir)
            self.assertIn("claude-opus-5-5  high", text)
            self.assertIn("input 1,234 cached 0 output 56", text)
            self.assertIn("claude-sonnet-5-5  low  fix complete", text)
            self.assertIn("effort-high", text)
            self.assertIn("   2  claude-opus-5-5  high", text)
            self.assertIn("classifier tokens: input 2,468", text)
            self.assertIn("worker tokens: input 900 cached 100 output 40", text)
            only_b = self.report(sdir, "--session", "bbbb")
            self.assertNotIn("aaaaaaaa", only_b)
            self.assertIn("   1  claude-opus-5-5  high", only_b)

    def test_route_with_session_is_logged_and_reported(self):
        with tempfile.TemporaryDirectory() as sdir:
            env = {"MER_STATE_DIR": sdir, "HOME": sdir}
            out = io.StringIO()
            argv = ["route", "--host", "opencode", "--role", "review", "--effort", "high", "--json"]
            self.assertEqual(main([*argv, "--session", "ses_abc", "check it"], env=env, out=out), 0)
            self.assertEqual(main([*argv, "check it"], env=env, out=io.StringIO()), 0)  # no session: no log
            self.assertEqual(len(list(Path(sdir).glob("*.log.jsonl"))), 1)
            text = self.report(sdir, "--session", "ses_abc")
            self.assertIn("review/explicit", text)
            self.assertIn("  high  ", text)

    def test_summarizes_advice_followed_and_classifier_health(self):
        now = time.time()
        spawn = {
            "event": "route",
            "target": "route",
            "latency_ms": 100,
            "advice": {"action": "spawn"},
            "decision": {"role": "plan", "backend": "jev", "model": "m", "applied_effort": "low"},
        }
        failed = {"event": "route", "target": "error", "latency_ms": 300, "classifier_causes": ["jev:HTTP 503"]}
        fallback = {
            **spawn,
            "latency_ms": 200,
            "classifier_fallback": True,
            "advice": {"action": "inline_same_model"},
            "classifier_causes": ["jev:HTTP 503"],
        }
        starts = [{"event": "subagent_start", "correlation": {"matched": m}} for m in (True, False, None)]
        with tempfile.TemporaryDirectory() as sdir:
            _log(sdir, "aaaaaaaa-1", *({**e, "ts": now} for e in (spawn, failed, fallback, *starts)))
            text = self.report(sdir)
            self.assertIn("advice: spawn 1 · inline_same_model 1", text)
            self.assertIn("subagents: matched 1 · mismatched 1 · unverified 1", text)
            self.assertIn("classifier: 3 routes · 1 errors · 1 fallbacks · latency avg 200 ms, p95 300 ms", text)
            self.assertIn("causes: jev:HTTP 503 2", text)

    def test_since_drops_older_events_and_rejects_bad_values(self):
        now = time.time()
        route = {"event": "route", "decision": {"role": "plan", "model": "m", "applied_effort": "low"}}
        with tempfile.TemporaryDirectory() as sdir:
            _log(sdir, "aaaaaaaa-1", {**route, "ts": now - 3 * 86400}, {**route, "ts": now - 60})
            self.assertIn("   2  m  low", self.report(sdir))
            self.assertIn("   1  m  low", self.report(sdir, "--since", "1d"))
            self.assertIn("no routed requests", self.report(sdir, "--since", "0m"))
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                self.report(sdir, "--since", "5x")

    def test_limit_picks_the_most_recent_rows_and_zero_lists_none(self):
        route = {"event": "route", "decision": {"role": "plan", "applied_effort": "low"}}
        with tempfile.TemporaryDirectory() as sdir:
            _log(
                sdir,
                "aaaaaaaa-1",
                *({**route, "ts": i, "decision": {**route["decision"], "model": f"m{i}"}} for i in (1, 2, 3)),
            )

            def rows(*argv):
                return [line for line in self.report(sdir, *argv).splitlines() if "aaaaaaaa" in line]

            self.assertEqual(len(rows("--limit", "2")), 2)
            self.assertIn("m3", rows("--limit", "1")[0])
            self.assertEqual(len(rows("--limit", "9")), 3)  # more than exist: all rows, not a wrapped slice
            self.assertEqual(rows("--limit", "0"), [])
            self.assertIn("   1  m1  low", self.report(sdir, "--limit", "0"))  # summary still printed
            for bad in ("-1", "x"):
                with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                    self.report(sdir, "--limit", bad)

    def test_empty_log_dir(self):
        with tempfile.TemporaryDirectory() as sdir:
            self.assertIn("no routed requests", self.report(sdir))


if __name__ == "__main__":
    unittest.main()

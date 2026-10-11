import io
import json
import tempfile
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

    def test_empty_log_dir(self):
        with tempfile.TemporaryDirectory() as sdir:
            self.assertIn("no routed requests", self.report(sdir))


if __name__ == "__main__":
    unittest.main()

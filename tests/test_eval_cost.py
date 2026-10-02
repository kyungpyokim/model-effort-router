import json
import tempfile
import unittest
from pathlib import Path

from evaluation import cost


def tok(inp, cached, out):
    return {"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {
        "input_tokens": inp, "cached_input_tokens": cached, "cache_write_input_tokens": 0, "output_tokens": out}}}}


def ctx(model):
    return {"type": "turn_context", "payload": {"model": model}}


def meta(sid, root, source="user"):
    return {"type": "session_meta", "payload": {"id": sid, "session_id": root, "thread_source": source}}


class RolloutTest(unittest.TestCase):
    def write(self, d, name, events):
        p = Path(d) / f"rollout-{name}.jsonl"
        p.write_text("\n".join(json.dumps(e) for e in events))
        return p

    def test_cumulative_growth_per_model_and_duplicate_token_count_counted_once(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.write(d, "a", [meta("T", "T"), ctx("luna"), tok(100, 40, 10), tok(100, 40, 10),  # duplicate
                                    ctx("sol"), tok(300, 140, 30)])
            self.assertEqual(cost.rollout_by_model(p), {
                "luna": {"input": 100, "cached_input": 40, "cache_write": 0, "output": 10},
                "sol": {"input": 200, "cached_input": 100, "cache_write": 0, "output": 20}})

    def test_run_sums_main_and_subagent_rollouts_and_prices_per_model(self):
        prices = {"luna": {"input": 1.0, "cached_input": 0.1, "output": 5.0}}
        with tempfile.TemporaryDirectory() as d:
            self.write(d, "main", [meta("T", "T"), ctx("luna"), tok(1_000_000, 500_000, 100_000)])
            self.write(d, "child", [meta("C", "T", "subagent"), ctx("terra"), tok(10, 0, 1)])
            rec = {"case_id": "c", "run": 1, "mode": "router", "thread_ids": ["T"],
                   "usage": {"classifier": {"input": 700, "cached_input": 0, "output": 100, "reasoning_output": 0}}}
            r = cost.run_cost(rec, d, prices)
            self.assertEqual((r["tokens"], r["unpriced"], r["usd"]), (1_100_011, ["terra"], None))  # never priced as 0
            self.assertEqual(r["classifier_tokens"], 800)
            prices["terra"] = {"input": 0.0, "cached_input": 0.0, "output": 0.0}
            self.assertAlmostEqual(cost.run_cost(rec, d, prices)["usd"], 0.5 + 0.05 + 0.5)

    def test_claude_record_uses_reported_cost_and_never_reads_rollouts(self):
        rec = {"case_id": "c", "run": 2, "mode": "router", "host": "claude", "cost_usd": 0.42, "thread_ids": ["S1"],
               "usage": {"total": 1800, "classifier": {"input": 700, "cached_input": 0, "output": 100, "reasoning_output": 0}}}
        r = cost.run_cost(rec, "/no/such/dir", {})
        self.assertEqual((r["tokens"], r["usd"], r["unpriced"], r["by_model"], r["classifier_tokens"], r["run"]),
                         (1000, 0.42, [], {}, 800, 2))
        r = cost.run_cost({**rec, "cost_usd": None, "usage": {"total": 500, "classifier": None}}, "/no/such/dir", {})
        self.assertEqual((r["tokens"], r["usd"], r["unpriced"], r["classifier_tokens"]), (500, None, ["claude:no_cost"], 0))

    def test_claude_tokens_and_by_model_come_from_model_usage_when_present(self):
        mu = {"claude-opus-5-5": {"input": 900, "cached_input": 800, "cache_write": 0, "output": 100},
              "claude-haiku-4-5": {"input": 50, "cached_input": 0, "cache_write": 0, "output": 5}}  # subagent/side-call included
        rec = {"case_id": "c", "run": 1, "mode": "baseline", "host": "claude", "cost_usd": 0.3, "model_usage": mu,
               "usage": {"total": 400, "classifier": None}}
        r = cost.run_cost(rec, "/no/such/dir", {})
        self.assertEqual((r["tokens"], r["usd"], r["by_model"]), (1055, 0.3, {"claude-opus-5-5": 1000, "claude-haiku-4-5": 55}))

    def test_codex_record_without_host_still_reads_rollouts(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(d, "main", [meta("T", "T"), ctx("luna"), tok(1000, 0, 100)])
            rec = {"case_id": "c", "run": 1, "mode": "baseline", "host": "codex", "cost_usd": 9.9, "thread_ids": ["T"],
                   "usage": {"classifier": None}}
            r = cost.run_cost(rec, d, {"luna": {"input": 1.0, "cached_input": 0.1, "output": 5.0}})
            self.assertEqual((r["tokens"], r["by_model"]), (1100, {"luna": 1100}))

    def test_summary_totals_only_cases_priced_in_every_mode(self):
        rows = [{"case_id": "a", "mode": "baseline", "tokens": 10, "usd": 1.0},
                {"case_id": "a", "mode": "router", "tokens": 4, "usd": 0.2},
                {"case_id": "b", "mode": "router", "tokens": 5, "usd": 0.1}]
        s = cost.summarize(rows)
        self.assertEqual((s["complete"], s["totals"]["router"]), (["a"], {"tokens": 4, "usd": 0.2}))
        self.assertIn("router vs baseline: tokens -60%, USD -80%", cost.to_markdown(s))


if __name__ == "__main__":
    unittest.main()

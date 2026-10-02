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

    def test_summary_totals_only_cases_priced_in_every_mode(self):
        rows = [{"case_id": "a", "mode": "baseline", "tokens": 10, "usd": 1.0},
                {"case_id": "a", "mode": "router", "tokens": 4, "usd": 0.2},
                {"case_id": "b", "mode": "router", "tokens": 5, "usd": 0.1}]
        s = cost.summarize(rows)
        self.assertEqual((s["complete"], s["totals"]["router"]), (["a"], {"tokens": 4, "usd": 0.2}))
        self.assertIn("router vs baseline: tokens -60%, USD -80%", cost.to_markdown(s))


if __name__ == "__main__":
    unittest.main()

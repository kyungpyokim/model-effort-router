from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]

# Load eval_router_performance
eval_perf_spec = importlib.util.spec_from_file_location(
    "eval_router_performance", ROOT / "scripts" / "eval_router_performance.py"
)
eval_perf = importlib.util.module_from_spec(eval_perf_spec)
assert eval_perf_spec.loader is not None
sys.modules[eval_perf_spec.name] = eval_perf
eval_perf_spec.loader.exec_module(eval_perf)

# Load eval_model_effort
eval_effort_spec = importlib.util.spec_from_file_location(
    "eval_model_effort", ROOT / "scripts" / "eval_model_effort.py"
)
eval_effort = importlib.util.module_from_spec(eval_effort_spec)
assert eval_effort_spec.loader is not None
sys.modules[eval_effort_spec.name] = eval_effort
eval_effort_spec.loader.exec_module(eval_effort)


class EvalRouterPerformanceTests(unittest.TestCase):
    def test_golden_benchmark_accuracy_and_safety(self):
        result = eval_perf.evaluate_rules_benchmark()
        summary = result["summary"]

        self.assertGreaterEqual(summary["total_benchmark_cases"], 30)
        self.assertEqual(summary["accuracy_pct"], 100.0)
        self.assertEqual(summary["safety_guardrail_compliance_pct"], 100.0)
        self.assertEqual(summary["passed_cases"], summary["total_benchmark_cases"])

    def test_benchmark_latency_and_throughput(self):
        result = eval_perf.evaluate_rules_benchmark()
        summary = result["summary"]

        # Mean latency should be under 1ms (1000us)
        self.assertLess(summary["latency_us_mean"], 1000.0)
        # Throughput should be at least 10,000 ops/sec
        self.assertGreater(summary["throughput_ops_sec"], 10000.0)

    def test_main_cli_returns_zero(self):
        ret = eval_perf.main(["--json"])
        self.assertEqual(ret, 0)


class EvalModelEffortTests(unittest.TestCase):
    def test_collect_profiles_and_audit(self):
        data = eval_effort.evaluate_profiles()

        self.assertGreater(data["total_profiles_defined"], 80)
        self.assertGreaterEqual(data["unique_model_effort_combos"], 15)
        self.assertGreaterEqual(data["plugin_agent_counts"]["antigravity"], 10)
        self.assertGreaterEqual(data["plugin_agent_counts"]["claude"], 10)
        self.assertGreaterEqual(data["plugin_agent_counts"]["codex"], 10)

    def test_platform_filter(self):
        data = eval_effort.evaluate_profiles(target_platform="antigravity")
        for p in data["profiles"]:
            self.assertEqual(p["platform"], "antigravity")

    def test_main_cli_returns_zero(self):
        ret = eval_effort.main(["--json"])
        self.assertEqual(ret, 0)


if __name__ == "__main__":
    unittest.main()

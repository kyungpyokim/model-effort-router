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

    def test_classifier_benchmark_scores_facts_and_unknown_transitions(self):
        expected_by_task = {case.task: case for case in eval_perf.GOLDEN_BENCHMARK_CASES}

        def classifier(task, platform):
            case = expected_by_task[task]
            facts = {**eval_perf._base_facts(), **case.facts}
            return eval_perf.router.validate_classifier_output({
                "task_type": case.task_type,
                "facts": facts,
                "delegability": 0,
                "evidence": [],
                "reason": "test classifier",
            })

        result = eval_perf.evaluate_classifier_benchmark(classifier=classifier)

        self.assertEqual(result["summary"]["total_benchmark_cases"], len(expected_by_task))
        self.assertEqual(result["summary"]["routing_accuracy_pct"], 100.0)
        self.assertEqual(result["summary"]["labelled_fact_accuracy_pct"], 100.0)
        self.assertGreater(result["summary"]["unknown_transitions"]["expected_unknown_to_unknown"], 0)

        unknown_only = eval_perf.evaluate_classifier_benchmark(
            classifier=classifier,
            case_names=("L3_unknown_module_boundary_needs_context",),
        )
        self.assertEqual(unknown_only["summary"]["total_benchmark_cases"], 1)

        def defaults_only(task, platform):
            case = expected_by_task[task]
            return eval_perf.router.validate_classifier_output({
                "task_type": case.task_type,
                "facts": eval_perf._base_facts(),
                "delegability": 0,
                "evidence": [],
                "reason": "defaults only",
            })

        biased = eval_perf.evaluate_classifier_benchmark(classifier=defaults_only)
        self.assertLess(
            biased["summary"]["labelled_fact_accuracy_pct"],
            biased["summary"]["all_fact_agreement_pct"],
        )

    def test_classifier_benchmark_measures_the_code_understanding_rung_end_to_end(self):
        cases = [c for c in eval_perf.GOLDEN_BENCHMARK_CASES if "requires_code_understanding" in c.facts]
        self.assertGreaterEqual(sum(c.facts["requires_code_understanding"] == "yes" for c in cases), 3)
        self.assertGreaterEqual(sum(c.facts["requires_code_understanding"] == "no" for c in cases), 3)
        by_task = {case.task: case for case in eval_perf.GOLDEN_BENCHMARK_CASES}

        def classifier_answering(understanding):
            def classify(task, platform):
                case = by_task[task]
                facts = {**eval_perf._base_facts(), **case.facts, "requires_code_understanding": understanding(case)}
                return eval_perf.router.validate_classifier_output({
                    "task_type": case.task_type, "facts": facts, "delegability": 0, "evidence": [], "reason": "stub",
                })
            return classify

        for platform, refined in (("codex", ("gpt-5.6-luna", "high")), ("claude-code", ("claude-sonnet-5", "low"))):
            with self.subTest(platform=platform):
                perfect = eval_perf.evaluate_classifier_benchmark(platform, classifier=classifier_answering(lambda c: {**eval_perf._base_facts(), **c.facts}["requires_code_understanding"]))
                summary = perfect["summary"]
                self.assertEqual((summary["profile_accuracy_pct"], summary["routing_accuracy_pct"]), (100.0, 100.0))
                self.assertEqual(summary["per_fact_accuracy_pct"]["requires_code_understanding"], 100.0)
                self.assertEqual(set(summary["code_understanding_confusion"]), {"yes->yes", "no->no"})
                yes_case = next(c for c in perfect["cases"] if c["name"] == "L2U_pattern_following_validation")
                self.assertEqual(yes_case["actual"]["profile"]["stages"], [refined])

                always_no = eval_perf.evaluate_classifier_benchmark(platform, classifier=classifier_answering(lambda c: "no"))["summary"]
                self.assertEqual(always_no["routing_accuracy_pct"], 100.0)  # the level never depends on this fact
                self.assertLess(always_no["profile_accuracy_pct"], 100.0)   # the implementer rung does
                self.assertIn("yes->no", always_no["code_understanding_confusion"])

                always_unknown = eval_perf.evaluate_classifier_benchmark(platform, classifier=classifier_answering(lambda c: "unknown"))["summary"]
                self.assertLess(always_unknown["profile_accuracy_pct"], 100.0)

    def test_an_unlabelled_rung_fact_is_not_graded_on_the_corpus_default(self):
        case = next(c for c in eval_perf.GOLDEN_BENCHMARK_CASES if c.name == "L2_model_tier_approval_confirmation")
        self.assertNotIn("requires_code_understanding", case.facts)

        def answering(value):
            def classify(task, platform):
                facts = {**eval_perf._base_facts(), **case.facts, "requires_code_understanding": value}
                return eval_perf.router.validate_classifier_output({
                    "task_type": case.task_type, "facts": facts, "delegability": 0, "evidence": [], "reason": "stub",
                })
            return classify

        for value in ("yes", "no", "unknown"):
            with self.subTest(value=value):
                summary = eval_perf.evaluate_classifier_benchmark(classifier=answering(value), case_names=(case.name,))["summary"]
                self.assertEqual(summary["profile_accuracy_pct"], 100.0)
                self.assertEqual(summary["code_understanding_confusion"], {})

    def test_classifier_benchmark_counts_fallbacks_and_reports_cost(self):
        def failing(task, platform):
            return eval_perf.router.fallback_classification("classifier down")

        result = eval_perf.evaluate_classifier_benchmark(classifier=failing, limit=3)
        summary = result["summary"]
        self.assertEqual((summary["classifier_fallbacks"], summary["classifier_calls"]), (3, 3))
        self.assertGreaterEqual(summary["seconds"], 0)
        self.assertTrue(all(case["source"] == "fallback" for case in result["cases"]))

    def test_rules_benchmark_routes_carry_the_refined_rung(self):
        data = eval_perf.evaluate_rules_benchmark()
        by_name = {case["name"]: case for case in data["cases"]}
        self.assertEqual(by_name["L2U_pattern_following_validation"]["platform_routes"]["codex"]["efforts"], ["high"])
        self.assertEqual(by_name["L2U_add_optional_field"]["platform_routes"]["codex"]["efforts"], ["medium"])


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

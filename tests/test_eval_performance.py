from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock

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


CASE_BY_TASK = {case.task: case for case in eval_perf.GOLDEN_BENCHMARK_CASES}
assert len(CASE_BY_TASK) == len(eval_perf.GOLDEN_BENCHMARK_CASES), "benchmark tasks must be unique"


def stub_classifier(facts_for, task_type_for=lambda case: case.task_type):
    """A deterministic classifier answering from the corpus: facts_for(case) returns the fact dict to give back."""
    def classify(task, platform):
        case = CASE_BY_TASK[task]
        return eval_perf.router.validate_classifier_output({
            "task_type": task_type_for(case), "facts": facts_for(case), "delegability": 0, "evidence": [], "reason": "stub",
        })
    return classify


def labelled_facts(case, **overrides):
    return {**eval_perf._base_facts(), **case.facts, **overrides}


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
        classifier = stub_classifier(labelled_facts)
        summary = eval_perf.evaluate_classifier_benchmark(classifier=classifier)["summary"]
        self.assertEqual((summary["total_benchmark_cases"], summary["graded_cases"]), (len(CASE_BY_TASK),) * 2)
        self.assertEqual((summary["routing_accuracy_pct"], summary["task_type_accuracy_pct"], summary["labelled_fact_accuracy_pct"]), (100.0,) * 3)
        self.assertGreater(summary["unknown_transitions"]["expected_unknown_to_unknown"], 0)

        unknown_only = eval_perf.evaluate_classifier_benchmark(
            classifier=classifier, case_names=("L3_unknown_module_boundary_unresolved",),
        )
        self.assertEqual([case["name"] for case in unknown_only["cases"]], ["L3_unknown_module_boundary_unresolved"])

        biased = eval_perf.evaluate_classifier_benchmark(classifier=stub_classifier(lambda case: eval_perf._base_facts()))["summary"]
        self.assertLess(biased["labelled_fact_accuracy_pct"], biased["all_fact_agreement_pct"])

    def test_a_classifier_that_omits_the_optional_fact_only_regresses_on_labelled_cases(self):
        def omitting(case):
            facts = labelled_facts(case)
            del facts["requires_code_understanding"]
            return facts

        summary = eval_perf.evaluate_classifier_benchmark(classifier=stub_classifier(omitting))["summary"]
        labelled = sum("requires_code_understanding" in case.facts for case in eval_perf.GOLDEN_BENCHMARK_CASES)
        self.assertEqual(summary["unknown_transitions"]["expected_known_to_unknown"], labelled)

    def test_an_unlabelled_fact_cannot_move_the_expected_level_or_tier(self):
        # An unlabelled fact following the classifier's own answer must not let a WRONG classifier answer on that
        # fact redefine what counts as correct: routing still grades against the case's own declared outcome, never
        # against evaluate_rules(graded_facts). Otherwise a classifier that over-escalates on any unlabelled fact
        # (here: a doc typo answered irreversible_or_ledger_or_crypto="yes") scores a perfect routing/profile match.
        case = next(c for c in eval_perf.GOLDEN_BENCHMARK_CASES if c.name == "L1_doc_typo_fix")
        self.assertEqual((case.expected_level, case.expected_tier), ("L1", "standard"))
        over_escalating = stub_classifier(lambda c: labelled_facts(c, irreversible_or_ledger_or_crypto="yes"))
        summary = eval_perf.evaluate_classifier_benchmark(classifier=over_escalating, case_names=(case.name,))["summary"]
        self.assertEqual((summary["routing_accuracy_pct"], summary["profile_accuracy_pct"]), (0.0, 0.0))

    def test_an_unlabelled_security_fact_cannot_redefine_the_expected_profile(self):
        case = next(c for c in eval_perf.GOLDEN_BENCHMARK_CASES if c.name == "L1_doc_typo_fix")
        over_escalating = stub_classifier(lambda c: labelled_facts(c, changes_security_or_payment_logic="yes"))
        summary = eval_perf.evaluate_classifier_benchmark(classifier=over_escalating, case_names=(case.name,))["summary"]
        self.assertEqual((summary["routing_accuracy_pct"], summary["profile_accuracy_pct"]), (0.0, 0.0))

    def test_extra_unresolved_facts_fail_routing_and_profile_without_changing_transition_metrics(self):
        # A route with any unresolved fact cannot execute, including one the corpus did not label. It must not
        # count as a routing or profile pass, but unknown-transition metrics still cover labelled facts only.
        case = next(c for c in eval_perf.GOLDEN_BENCHMARK_CASES if c.name == "L5E_security_oauth_token_refresh")
        self.assertNotIn("crosses_module_boundary", case.facts)
        divergent = {"crosses_module_boundary": "unknown", "blast_radius": "broad", "changes_trust_boundary": "yes"}
        kwargs = {"case_names": (case.name,)}
        perfect = eval_perf.evaluate_classifier_benchmark(classifier=stub_classifier(labelled_facts), **kwargs)["summary"]
        summary = eval_perf.evaluate_classifier_benchmark(
            classifier=stub_classifier(lambda c: labelled_facts(c, **divergent)), **kwargs,
        )["summary"]
        self.assertEqual((summary["routing_accuracy_pct"], summary["profile_accuracy_pct"]), (0.0, 0.0))
        self.assertEqual(summary["unknown_transitions"], perfect["unknown_transitions"])

        # A labelled fact still fails routing: the classifier calling a security change harmless drops the tier.
        # graded_facts feeds the profile check too, so the tier drop must also route to a different model+effort.
        missed = eval_perf.evaluate_classifier_benchmark(
            classifier=stub_classifier(lambda c: labelled_facts(c, changes_security_or_payment_logic="no")), **kwargs,
        )["summary"]
        self.assertEqual((missed["routing_accuracy_pct"], missed["profile_accuracy_pct"]), (0.0, 0.0))

    def test_missing_expected_unresolved_fact_fails_routing_and_profile(self):
        case = next(c for c in eval_perf.GOLDEN_BENCHMARK_CASES if c.name == "L3_unknown_module_boundary_unresolved")
        self.assertEqual(case.expected_unresolved, ("crosses_module_boundary",))
        summary = eval_perf.evaluate_classifier_benchmark(
            classifier=stub_classifier(lambda c: labelled_facts(c, crosses_module_boundary="no")),
            case_names=(case.name,),
        )["summary"]
        self.assertEqual((summary["routing_accuracy_pct"], summary["profile_accuracy_pct"]), (0.0, 0.0))

    def test_swapping_implementation_and_local_refactoring_does_not_fail_routing(self):
        swap = {"implementation": "local_refactoring", "local_refactoring": "implementation"}
        summary = eval_perf.evaluate_classifier_benchmark(
            classifier=stub_classifier(labelled_facts, lambda case: swap.get(case.task_type, case.task_type)),
        )["summary"]
        self.assertEqual((summary["routing_accuracy_pct"], summary["profile_accuracy_pct"]), (100.0, 100.0))
        self.assertLess(summary["task_type_accuracy_pct"], 100.0)

    def test_classifier_benchmark_measures_the_code_understanding_rung_end_to_end(self):
        cases = [c for c in eval_perf.GOLDEN_BENCHMARK_CASES if "requires_code_understanding" in c.facts]
        self.assertGreaterEqual(sum(c.facts["requires_code_understanding"] == "yes" for c in cases), 3)
        self.assertGreaterEqual(sum(c.facts["requires_code_understanding"] == "no" for c in cases), 3)

        def answering(value):
            return stub_classifier(lambda case: labelled_facts(case, requires_code_understanding=value(case)))

        for platform, refined in (("codex", ("gpt-5.6-luna", "high")), ("claude-code", ("claude-sonnet-5", "low"))):
            with self.subTest(platform=platform):
                perfect = eval_perf.evaluate_classifier_benchmark(platform, classifier=stub_classifier(labelled_facts))
                summary = perfect["summary"]
                self.assertEqual((summary["profile_accuracy_pct"], summary["routing_accuracy_pct"]), (100.0, 100.0))
                self.assertTrue(summary["refinement_coverage"])
                self.assertEqual(summary["per_fact_accuracy_pct"]["requires_code_understanding"], 100.0)
                self.assertEqual(set(summary["code_understanding_confusion"]), {"yes->yes", "no->no"})
                yes_case = next(c for c in perfect["cases"] if c["name"] == "L2U_pattern_following_validation")
                # L2 code changes carry a judge plan first; the refined rung is the implementer stage after it.
                stages = yes_case["actual"]["profile"]["stages"]
                self.assertEqual(len(stages), 2)
                self.assertEqual(stages[-1], refined)

                always_no = eval_perf.evaluate_classifier_benchmark(platform, classifier=answering(lambda c: "no"))["summary"]
                self.assertEqual(always_no["routing_accuracy_pct"], 100.0)  # the level never depends on this fact
                self.assertLess(always_no["profile_accuracy_pct"], 100.0)   # the implementer rung does
                self.assertIn("yes->no", always_no["code_understanding_confusion"])

                always_unknown = eval_perf.evaluate_classifier_benchmark(platform, classifier=answering(lambda c: "unknown"))["summary"]
                self.assertLess(always_unknown["profile_accuracy_pct"], 100.0)

    def test_unlabelled_optional_fact_follows_the_classifiers_own_answer_for_profile(self):
        # requires_code_understanding is optional and rarely labelled; graded_facts must blend in the
        # classifier's own answer for it, not the corpus default "unknown" -- otherwise a classifier that
        # correctly answers "yes" scores a profile miss purely because the corpus never labelled this fact.
        case_name = "L2_unknown_security_change_is_not_a_floor"
        classifier = stub_classifier(lambda case: labelled_facts(case, requires_code_understanding="yes"))
        summary = eval_perf.evaluate_classifier_benchmark("codex", classifier=classifier, case_names=(case_name,))["summary"]
        self.assertEqual(summary["profile_accuracy_pct"], 100.0)

    def test_antigravity_has_no_refinements_so_its_profile_is_flagged_uninformative(self):
        summary = eval_perf.evaluate_classifier_benchmark(
            "antigravity", classifier=stub_classifier(lambda case: labelled_facts(case, requires_code_understanding="no")),
        )["summary"]
        self.assertFalse(summary["refinement_coverage"])

    def test_a_routing_error_on_both_sides_is_a_profile_miss(self):
        error = {"error": "broken config"}
        with mock.patch.object(eval_perf, "_route_profile", return_value=error):
            summary = eval_perf.evaluate_classifier_benchmark(classifier=stub_classifier(labelled_facts), limit=3)["summary"]
        self.assertEqual(summary["profile_accuracy_pct"], 0.0)

    def test_classifier_fallbacks_are_reported_not_graded(self):
        def failing(task, platform):
            return eval_perf.router.fallback_classification("classifier down")

        summary = eval_perf.evaluate_classifier_benchmark(classifier=failing, limit=3)["summary"]
        self.assertEqual((summary["classifier_fallbacks"], summary["classifier_calls"], summary["graded_cases"]), (3, 3, 0))
        self.assertEqual((summary["routing_accuracy_pct"], summary["unknown_transitions"]["expected_unknown_to_known"]), (0.0, 0))

        good = stub_classifier(labelled_facts)
        outage = eval_perf.evaluate_classifier_benchmark(
            classifier=lambda task, platform: failing(task, platform) if CASE_BY_TASK[task].name == "L2_simple_bug_fix" else good(task, platform),
        )
        self.assertEqual(outage["summary"]["routing_accuracy_pct"], 100.0)  # graded cases are unaffected by the outage
        self.assertEqual(outage["summary"]["classifier_fallbacks"], 1)

    def test_live_exit_code_fails_on_a_miss_and_on_an_outage(self):
        def run(**overrides):
            summary = {
                "routing_accuracy_pct": 100.0, "profile_accuracy_pct": 100.0, "refinement_coverage": True,
                "classifier_fallbacks": 0, "task_type_accuracy_pct": 100.0, "graded_cases": 1, "passed_cases": 1,
                "total_benchmark_cases": 1, "labelled_fact_accuracy_pct": 100.0, "classifier_calls": 1, "seconds": 0,
                "code_understanding_confusion": {}, "platform": "codex",
                "unknown_transitions": {"expected_unknown_to_unknown": 0, "expected_unknown_to_known": 0, "expected_known_to_unknown": 0},
                **overrides,
            }
            with mock.patch.object(eval_perf, "evaluate_classifier_benchmark", return_value={"summary": summary, "cases": []}):
                return eval_perf.main(["--live-classifier", "--json"])

        with mock.patch("builtins.print"):
            self.assertEqual(run(), 0)
            self.assertEqual(run(routing_accuracy_pct=94.4), 1)
            self.assertEqual(run(profile_accuracy_pct=94.4), 1)
            self.assertEqual(run(classifier_fallbacks=2), 1)
            self.assertEqual(run(profile_accuracy_pct=94.4, refinement_coverage=False), 0)

    def test_cli_rejects_bad_limits_and_case_names(self):
        for argv in (["--live-classifier", "--limit", "0"], ["--live-classifier", "--case", "nope"], ["--live-classifier", "--limit", "2", "--case", "L2_simple_bug_fix"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                eval_perf.main(argv)

    def test_rules_benchmark_routes_carry_the_refined_rung(self):
        data = eval_perf.evaluate_rules_benchmark()
        by_name = {case["name"]: case for case in data["cases"]}
        # Efforts are per stage: the Sol plan (high) first, then the implementer, which carries the refined rung.
        self.assertEqual(by_name["L2U_pattern_following_validation"]["platform_routes"]["codex"]["efforts"], ["high", "high"])
        self.assertEqual(by_name["L2U_add_optional_field"]["platform_routes"]["codex"]["efforts"], ["high", "medium"])


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

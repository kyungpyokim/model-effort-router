#!/usr/bin/env python3
"""Comprehensive performance and accuracy evaluation benchmark for Model Effort Router."""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
ROUTER_PATH = BUNDLE_ROOT / "scripts" / "router.py"
CONFIG_PATH = BUNDLE_ROOT / "config" / "model-map.json"

spec = importlib.util.spec_from_file_location("router", ROUTER_PATH)
router = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = router
spec.loader.exec_module(router)


# Every fact DIFFICULTY_RULES conditions on: the set that can move level or tier.
# requires_code_understanding is deliberately excluded (it only picks the implementer rung).
ROUTING_RELEVANT_FACTS = frozenset(
    fact for _rule_level, _name, conditions in router.DIFFICULTY_RULES for fact in conditions
) | {"mechanical_only", "files_touched"}


_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from benchmark_corpus import BenchmarkCase, GOLDEN_BENCHMARK_CASES


_FACT_DEFAULT_OVERRIDES = {
    "fix_or_result_known": "yes",
    "files_touched": "1",
    "security_domain": "none",
    "blast_radius": "narrow",
    **router.OPTIONAL_FACT_DEFAULTS,
}


def _base_facts() -> dict[str, str]:
    """Every router.FACTS entry at its safest default ('nothing risky here'); cases override on top."""
    return {name: _FACT_DEFAULT_OVERRIDES.get(name, "no") for name in router.FACTS}


def evaluate_rules_benchmark() -> dict:
    """Evaluates rule precision, safety floors, and latency on the golden benchmark dataset."""
    config = router.load_config(CONFIG_PATH)
    base_facts = _base_facts()

    results = []
    latencies_us = []
    safety_violations = 0
    accuracy_passes = 0

    for case in GOLDEN_BENCHMARK_CASES:
        merged_facts = {**base_facts, **case.facts}
        t0 = time.perf_counter_ns()
        level, tier, matched_rules, unresolved = router.evaluate_rules(merged_facts)
        t_elapsed_us = (time.perf_counter_ns() - t0) / 1000.0
        latencies_us.append(t_elapsed_us)

        # Accuracy check
        tier_match = (tier == case.expected_tier)
        context_match = (unresolved == case.expected_unresolved)
        level_match = (level == case.expected_level)
        passed = level_match and tier_match and context_match
        if passed:
            accuracy_passes += 1

        # Safety floor checks
        has_security = merged_facts.get("changes_security_or_payment_logic") == "yes"
        if has_security and tier == "standard":
            safety_violations += 1

        has_api_or_migration = (
            merged_facts.get("changes_public_api_contract") == "yes"
            or merged_facts.get("changes_persisted_data") == "yes"
        )
        if has_api_or_migration and router.LEVELS.index(level) < router.LEVELS.index("L4"):
            safety_violations += 1

        # Routing check for 3 platforms
        platform_routes = {}
        for plat in ("codex", "claude-code", "antigravity"):
            mock_classification = router.Classification(
                task_type=case.task_type,
                level=level,
                risk_flags=router.risk_flags_from_facts(merged_facts),
                reason="benchmark",
                source="test",
                risk_tier=tier,
                facts=dict(merged_facts),
            )
            route_res = router.route(
                case.task,
                plat,
                config,
                classifier=lambda _t, c=mock_classification: c,
                critical=(tier == "critical"),
            )
            platform_routes[plat] = {
                "level": route_res.level,
                "stages": [s["model"] for s in route_res.stages],
                "efforts": [s["effort"] for s in route_res.stages],
                "mode": route_res.mode,
            }

        results.append({
            "name": case.name,
            "passed": passed,
            "level": level,
            "risk_tier": tier,
            "matched_rules": matched_rules,
            "unresolved": list(unresolved),
            "latency_us": round(t_elapsed_us, 2),
            "platform_routes": platform_routes,
        })

    total_cases = len(GOLDEN_BENCHMARK_CASES)
    accuracy_pct = (accuracy_passes / total_cases) * 100.0
    safety_compliance_pct = ((total_cases - safety_violations) / total_cases) * 100.0

    # Throughput test: run 50,000 evaluations
    throughput_iterations = 50000
    t_start = time.perf_counter()
    sample_facts = {**base_facts, "files_touched": "2-5", "changes_security_or_payment_logic": "yes"}
    for _ in range(throughput_iterations):
        router.evaluate_rules(sample_facts)
    t_total = time.perf_counter() - t_start
    throughput_ops = throughput_iterations / t_total

    return {
        "summary": {
            "total_benchmark_cases": total_cases,
            "passed_cases": accuracy_passes,
            "accuracy_pct": round(accuracy_pct, 2),
            "safety_guardrail_compliance_pct": round(safety_compliance_pct, 2),
            "throughput_ops_sec": round(throughput_ops, 1),
            "latency_us_mean": round(statistics.mean(latencies_us), 2),
            "latency_us_p50": round(statistics.median(latencies_us), 2),
            "latency_us_p95": round(statistics.quantiles(latencies_us, n=20)[18], 2),
            "latency_us_p99": round(statistics.quantiles(latencies_us, n=100)[98], 2),
        },
        "cases": results,
    }


def _route_profile(config: dict, platform: str, task: str, classification: router.Classification, critical: bool) -> dict:
    """Model/effort per stage and mode a classification routes to; a routing error is reported, not raised."""
    try:
        result = router.route(task, platform, config, classifier=lambda _t: classification, critical=critical)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"mode": result.mode, "stages": [(stage["model"], stage["effort"]) for stage in result.stages]}


def _pct(hit: int, total: int) -> float:
    return round((hit / total) * 100, 2) if total else 0.0


# Relative cost proxy for routing economics (not real billing): level weights
# double per rung, and the elevated/critical planning uplift multiplies. It answers
# "how much more expensive is the actual routing than the labelled routing?"
LEVEL_COST = {"L1": 1.0, "L2": 2.0, "L3": 4.0, "L4": 8.0, "L5": 16.0}
TIER_MULT = {"standard": 1.0, "elevated": 1.5, "critical": 2.0}


def _route_cost(level: str, tier: str) -> float:
    return LEVEL_COST.get(level, 2.0) * TIER_MULT.get(tier, 1.0)


def _routing_direction_metrics(graded_cases: list[dict]) -> dict:
    """Failure decomposition and cost metrics over graded routing outcomes.

    Splits misses into over-route (actual level above expected), under-route
    (below), and tier-only (same level, different tier); measures how far
    over-routes jump, tier recall for the expensive tiers, cost inflation under
    the LEVEL_COST proxy, which rules most often caused the promotion, and
    false-positive counts for the facts that escalate.
    """
    total = len(graded_cases)
    level_hits = sum(1 for g in graded_cases if g.get("level_passed", g["expected"]["level"] == g["actual"]["level"]))
    tier_hits = sum(1 for g in graded_cases if g.get("tier_passed", g["expected"]["risk_tier"] == g["actual"]["risk_tier"]))
    within_one = sum(1 for g in graded_cases if abs(g.get("level_distance", 0)) <= 1)
    over_cases = [g for g in graded_cases if g.get("level_distance", 0) > 0]
    under_cases = [g for g in graded_cases if g.get("level_distance", 0) < 0]
    tier_only = sum(1 for g in graded_cases if g.get("tier_only_mismatch", False))
    distances = [g.get("level_distance", 0) for g in graded_cases]
    over_distances = [g.get("level_distance", 0) for g in over_cases]

    expected_critical = [g for g in graded_cases if g["expected"]["risk_tier"] == "critical"]
    expected_elevated = [g for g in graded_cases if g["expected"]["risk_tier"] == "elevated"]
    critical_recall = sum(1 for g in expected_critical if g["actual"]["risk_tier"] == "critical")
    elevated_recall = sum(1 for g in expected_elevated if g["actual"]["risk_tier"] in ("elevated", "critical"))

    expected_cost = sum(_route_cost(g["expected"]["level"], g["expected"]["risk_tier"]) for g in graded_cases)
    actual_cost = sum(_route_cost(g["actual"]["level"], g["actual"]["risk_tier"]) for g in graded_cases)

    promoting: dict[str, int] = {}
    for g in graded_cases:
        for rule in g.get("promoting_rules", []):
            promoting[rule] = promoting.get(rule, 0) + 1

    fp_counts: dict[str, int] = {}
    fn_counts: dict[str, int] = {}

    def tally_fp(fact: str, is_fp, is_fn) -> None:
        for g in graded_cases:
            item = g.get("facts", {}).get(fact)
            if not item:
                continue
            exp, act = item.get("expected"), item.get("actual")
            if is_fp(exp, act):
                fp_counts[fact] = fp_counts.get(fact, 0) + 1
            if is_fn(exp, act):
                fn_counts[fact] = fn_counts.get(fact, 0) + 1

    tally_fp("silent_failure_material_harm", lambda e, a: e != "yes" and a == "yes", lambda e, a: e == "yes" and a != "yes")
    tally_fp("blast_radius", lambda e, a: e != "broad" and a == "broad", lambda e, a: e == "broad" and a != "broad")
    tally_fp("files_touched", lambda e, a: e in ("0", "1", "unknown") and a in ("2-5", "6+"), lambda e, a: e in ("2-5", "6+") and a not in ("2-5", "6+"))
    tally_fp("crosses_module_boundary", lambda e, a: e != "yes" and a == "yes", lambda e, a: e == "yes" and a != "yes")
    tally_fp("crosses_service_boundary", lambda e, a: e != "yes" and a == "yes", lambda e, a: e == "yes" and a != "yes")
    tally_fp("changes_security_or_payment_logic", lambda e, a: e != "yes" and a == "yes", lambda e, a: e == "yes" and a != "yes")
    tally_fp("reviews_security_sensitive_code", lambda e, a: e != "yes" and a == "yes", lambda e, a: e == "yes" and a != "yes")
    tally_fp("changes_public_api_contract", lambda e, a: e != "yes" and a == "yes", lambda e, a: e == "yes" and a != "yes")
    tally_fp("changes_persisted_data", lambda e, a: e != "yes" and a == "yes", lambda e, a: e == "yes" and a != "yes")
    tally_fp("needs_new_structure", lambda e, a: e != "yes" and a == "yes", lambda e, a: e == "yes" and a != "yes")
    tally_fp("intermittent_or_concurrency", lambda e, a: e != "yes" and a == "yes", lambda e, a: e == "yes" and a != "yes")

    return {
        "level_accuracy_pct": _pct(level_hits, total),
        "tier_accuracy_pct": _pct(tier_hits, total),
        "level_plus_minus_1_accuracy_pct": _pct(within_one, total),
        "over_route_count": len(over_cases),
        "over_route_pct": _pct(len(over_cases), total),
        "under_route_count": len(under_cases),
        "under_route_pct": _pct(len(under_cases), total),
        "tier_only_mismatch_count": tier_only,
        "mean_signed_level_distance": round(sum(distances) / total, 3) if total else 0.0,
        "mean_over_route_distance": round(sum(over_distances) / len(over_distances), 3) if over_distances else 0.0,
        "max_over_route_distance": max(over_distances) if over_distances else 0,
        "critical_recall_pct": _pct(critical_recall, len(expected_critical)),
        "critical_recall_counts": [critical_recall, len(expected_critical)],
        "elevated_recall_pct": _pct(elevated_recall, len(expected_elevated)),
        "elevated_recall_counts": [elevated_recall, len(expected_elevated)],
        "expected_cost": round(expected_cost, 2),
        "actual_cost": round(actual_cost, 2),
        "cost_inflation": round(actual_cost / expected_cost, 3) if expected_cost else 0.0,
        "promoting_rule_counts": dict(sorted(promoting.items(), key=lambda kv: (-kv[1], kv[0]))),
        "fact_fp_counts": dict(sorted(fp_counts.items())),
        "fact_fn_counts": dict(sorted(fn_counts.items())),
    }


def _grade_case(case: BenchmarkCase, actual: router.Classification, config: dict, platform: str, base_facts: dict[str, str]) -> dict:
    """Grade one classifier answer against its labels: fact agreement, level/tier, and the routed model+effort."""
    expected_facts = {**base_facts, **case.facts}
    per_fact = {name: {"expected": expected, "actual": actual.facts.get(name)} for name, expected in expected_facts.items()}
    # Routing grades against the case's own declared outcome, never against evaluate_rules() re-run on a fact set
    # blended with the classifier's own unlabelled-fact answers: that would let a wrong answer on any unlabelled
    # fact silently redefine what counts as correct (an over-escalating classifier grading itself as accurate).
    # A route with any unresolved fact is not executable, so the actual set must exactly match the case's
    # declared unresolved set. Unknown-transition metrics remain labelled-fact-only in _tally_facts.
    unresolved_expected = set(case.expected_unresolved)
    unresolved_actual = set(actual.unresolved)
    # The Jev SystemOne path asks a noul fact as a probability and can only answer yes or no, so a
    # labelled unknown on one of those facts is unrepresentable there rather than a classifier miss:
    # scoring it would measure the output schema, not the model. Exclude exactly those facts from the
    # comparison, count them separately in the summary, and still compare every fact the path can
    # leave unknown (choice facts, and anything the classifier's own answer left open). Strict
    # accuracy, which counts an unrepresentable unknown as a miss, stays in the summary beside it.
    unrepresentable = unresolved_expected & set(router.NOUL_FACTS) if actual.source == "jev" else set()
    expected_comparable = unresolved_expected - unrepresentable
    actual_comparable = unresolved_actual - unrepresentable
    unresolved_applicable = bool(expected_comparable) or bool(actual_comparable)
    unresolved_match = (actual_comparable == expected_comparable) if unresolved_applicable else None
    # task_type is graded on its own: implementation and local_refactoring route identically, so a swap must not fail routing.
    routing_match = (
        actual.level == case.expected_level
        and actual.risk_tier == case.expected_tier
        and unresolved_match is not False
    )
    # The profile check still follows the classifier's own answer on an unlabelled fact (e.g. requires_code_understanding,
    # which never changes level/tier but does pick the implementer rung): grading it against a corpus default would
    # fail a classifier for guessing something the case never labelled, on a fact routing itself doesn't depend on.
    graded_facts = {
        **expected_facts,
        **{
            name: actual.facts[name] for name in router.OPTIONAL_FACT_DEFAULTS
            if name not in case.facts and actual.facts.get(name) is not None
        },
    }
    expected_classification = router.Classification(
        task_type=case.task_type, level=case.expected_level, risk_flags=router.risk_flags_from_facts(graded_facts),
        reason="labelled", source="test", facts=graded_facts, risk_tier=case.expected_tier,
    )
    expected_profile = _route_profile(config, platform, case.task, expected_classification, case.expected_tier == "critical")
    actual_profile = _route_profile(config, platform, case.task, actual, actual.risk_tier == "critical")

    downward_level = router.LEVELS.index(actual.level) < router.LEVELS.index(case.expected_level)
    downward_tier = router.RISK_TIERS.index(actual.risk_tier) < router.RISK_TIERS.index(case.expected_tier)
    level_distance = router.LEVELS.index(actual.level) - router.LEVELS.index(case.expected_level)
    upward_level = level_distance > 0
    tier_only_mismatch = level_distance == 0 and actual.risk_tier != case.expected_tier
    expected_flags = router.risk_flags_from_facts(expected_facts)
    missing_flags = [flag for flag, exp in expected_flags.items() if exp and not actual.risk_flags.get(flag, False)]
    inspect_misclassification = actual.task_type == "inspect" and case.task_type != "inspect"
    unknown_facts_count = sum(1 for v in actual.facts.values() if v == "unknown")
    try:
        _, _, expected_matched, _ = router.evaluate_rules(expected_facts)
    except Exception:
        expected_matched = []
    actual_matched = list(actual.matched_rules or ())
    promoting_rules = [r for r in actual_matched if r not in expected_matched]

    return {
        "name": case.name,
        "source": actual.source,
        "graded": True,
        # A case where every routing-relevant fact was explicitly decided is fair grading ground for
        # routing accuracy; one that still leans on the "no/none/narrow" default for some fact would
        # let the classifier's own (possibly reasonable) read of that unaddressed fact fail the case
        # even when the fact was never actually settled by a human.
        "fully_labelled": ROUTING_RELEVANT_FACTS.issubset(case.facts),
        "passed": routing_match,
        "unresolved_match": unresolved_match,
        "unresolved_match_strict": unresolved_expected == unresolved_actual,
        "unresolved_applicable": unresolved_applicable,
        "unresolved_noul_unrepresentable": sorted(unrepresentable),
        "task_type_passed": actual.task_type == case.task_type,
        "level_passed": actual.level == case.expected_level,
        "tier_passed": actual.risk_tier == case.expected_tier,
        "level_distance": level_distance,
        "upward_level": upward_level,
        "tier_only_mismatch": tier_only_mismatch,
        "expected_matched": list(expected_matched),
        "actual_matched": actual_matched,
        "promoting_rules": promoting_rules,
        # A routing error on both sides is a broken config, never a match.
        "profile_passed": unresolved_match is not False and "error" not in actual_profile and expected_profile == actual_profile,
        "expected": {
            "task_type": case.task_type, "level": case.expected_level, "risk_tier": case.expected_tier,
            "unresolved": list(case.expected_unresolved), "profile": expected_profile,
        },
        "actual": {
            "task_type": actual.task_type, "level": actual.level, "risk_tier": actual.risk_tier,
            "unresolved": list(actual.unresolved), "profile": actual_profile,
        },
        "facts": per_fact,
        "safety": {
            "downward_level": downward_level,
            "downward_tier": downward_tier,
            "missing_flags": missing_flags,
            "inspect_misclassification": inspect_misclassification,
            "unknown_facts_count": unknown_facts_count,
            "safety_violation": downward_tier or bool(missing_flags) or downward_level or inspect_misclassification,
        },
    }


def _tally_facts(case: BenchmarkCase, graded: dict, tally: dict) -> None:
    for name, item in graded["facts"].items():
        agree = item["expected"] == item["actual"]
        tally["all_matches"] += agree
        tally["all_total"] += 1
        if name in case.facts:
            counts = tally["per_fact"].setdefault(name, {"matches": 0, "total": 0})
            counts["matches"] += agree
            counts["total"] += 1
        if item["actual"] is None or name not in case.facts:
            continue  # a missing fact resolved nothing, and an unlabelled one has no expected answer to move away from
        if item["expected"] == "unknown":
            tally["unknown"]["expected_unknown_to_unknown" if item["actual"] == "unknown" else "expected_unknown_to_known"] += 1
        elif item["actual"] == "unknown":
            tally["unknown"]["expected_known_to_unknown"] += 1
    if "requires_code_understanding" in case.facts:
        key = f"{case.facts['requires_code_understanding']}->{graded['facts']['requires_code_understanding']['actual']}"
        tally["confusion"][key] = tally["confusion"].get(key, 0) + 1


def evaluate_classifier_benchmark(
    platform: str = "codex",
    classifier: Callable[[str, str], router.Classification] | None = None,
    limit: int | None = None,
    case_names: tuple[str, ...] | None = None,
) -> dict:
    """Compare live classifier facts and routing against the human-labelled corpus.

    ``classifier`` keeps this deterministic in unit tests; omitted, it invokes the
    platform's real semantic preflight and therefore spends model usage. A case where the
    classifier fell back (down, rate-limited, timed out) is reported but not graded: an
    outage must not read as an accuracy regression.
    """
    if platform not in ("codex", "claude-code", "antigravity"):
        raise ValueError(f"unknown platform: {platform}")
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")

    cases = GOLDEN_BENCHMARK_CASES
    if case_names:
        wanted = set(case_names)
        cases = [case for case in cases if case.name in wanted]
        unknown = wanted - {case.name for case in cases}
        if unknown:
            raise ValueError(f"unknown benchmark cases: {', '.join(sorted(unknown))}")
    cases = cases[:limit]
    base_facts = _base_facts()
    classifier = classifier or router.classify_task
    config = router.load_config(CONFIG_PATH)
    tally = {
        "all_matches": 0, "all_total": 0, "per_fact": {}, "confusion": {},
        "unknown": {"expected_unknown_to_unknown": 0, "expected_unknown_to_known": 0, "expected_known_to_unknown": 0},
    }
    results = []
    started = time.perf_counter()
    for case in cases:
        case_started = time.perf_counter()
        actual = classifier(case.task, platform)
        case_seconds = round(time.perf_counter() - case_started, 2)
        if actual.source == "fallback":
            results.append({"name": case.name, "source": "fallback", "graded": False, "seconds": case_seconds})
            continue
        graded = _grade_case(case, actual, config, platform, base_facts)
        graded["seconds"] = case_seconds
        _tally_facts(case, graded, tally)
        results.append(graded)

    graded_cases = [item for item in results if item["graded"]]
    total = len(graded_cases)
    labelled_matches = sum(counts["matches"] for counts in tally["per_fact"].values())
    labelled_total = sum(counts["total"] for counts in tally["per_fact"].values())

    downward_levels = sum(item.get("safety", {}).get("downward_level", False) for item in graded_cases)
    downward_tiers = sum(item.get("safety", {}).get("downward_tier", False) for item in graded_cases)
    safety_violations = sum(item.get("safety", {}).get("safety_violation", False) for item in graded_cases)
    inspect_misclassifications = sum(item.get("safety", {}).get("inspect_misclassification", False) for item in graded_cases)
    total_unknowns = sum(item.get("safety", {}).get("unknown_facts_count", 0) for item in graded_cases)
    total_facts = total * len(router.FACTS)
    unresolved_applicable_cases = sum(1 for item in graded_cases if item.get("unresolved_applicable"))
    unresolved_matched_cases = sum(1 for item in graded_cases if item.get("unresolved_match") is True)
    noul_unrepresentable_facts = sum(len(item.get("unresolved_noul_unrepresentable", [])) for item in graded_cases)
    noul_unrepresentable_cases = sum(1 for item in graded_cases if item.get("unresolved_noul_unrepresentable"))
    strict_passed = sum(
        1 for item in graded_cases
        if item["level_passed"] and item["tier_passed"] and item.get("unresolved_match_strict")
    )

    by_provider = {}
    for src in sorted(set(item["source"] for item in results if item.get("source"))):
        src_cases = [item for item in graded_cases if item.get("source") == src]
        src_total = len(src_cases)
        if src_total:
            by_provider[src] = {
                "graded_cases": src_total,
                "passed_cases": sum(item["passed"] for item in src_cases),
                "routing_accuracy_pct": _pct(sum(item["passed"] for item in src_cases), src_total),
                "safety_violations": sum(item.get("safety", {}).get("safety_violation", False) for item in src_cases),
                "downward_level_pct": _pct(sum(item.get("safety", {}).get("downward_level", False) for item in src_cases), src_total),
                "downward_tier_discrepancies": sum(item.get("safety", {}).get("downward_tier", False) for item in src_cases),
                "inspect_misclassifications": sum(item.get("safety", {}).get("inspect_misclassification", False) for item in src_cases),
                "unknown_facts_pct": _pct(sum(item.get("safety", {}).get("unknown_facts_count", 0) for item in src_cases), src_total * len(router.FACTS)),
            }

    fully_labelled_cases = [item for item in graded_cases if item["fully_labelled"]]
    fl_total = len(fully_labelled_cases)
    direction = _routing_direction_metrics(graded_cases)

    return {
        "summary": {
            "platform": platform,
            "total_benchmark_cases": len(cases),
            "graded_cases": total,
            "passed_cases": sum(item["passed"] for item in graded_cases),
            # The previous routing rule, kept visible: it also demanded that a labelled unknown the
            # live path cannot answer (a noul fact, yes/no only) came back unknown.
            "routing_accuracy_strict_pct": _pct(strict_passed, total),
            "unresolved_applicable_cases": unresolved_applicable_cases,
            "unresolved_matched_cases": unresolved_matched_cases,
            "noul_unknown_unrepresentable_cases": noul_unrepresentable_cases,
            "noul_unknown_unrepresentable_facts": noul_unrepresentable_facts,
            "routing_accuracy_pct": _pct(sum(item["passed"] for item in graded_cases), total),
            # Scoped to cases where every routing-relevant fact was explicitly decided, not
            # defaulted: the classifier's actual routing skill, without corpus gaps counting
            # against it. See "fully_labelled" on each case.
            "fully_labelled_cases": fl_total,
            "routing_accuracy_on_fully_labelled_pct": _pct(
                sum(item["passed"] for item in fully_labelled_cases), fl_total
            ),
            "task_type_accuracy_pct": _pct(sum(item["task_type_passed"] for item in graded_cases), total),
            "profile_accuracy_pct": _pct(sum(item["profile_passed"] for item in graded_cases), total),
            # Without refinements on this platform the profile cannot see an implementer-rung miss.
            "refinement_coverage": bool(router.load_refinements(config, platform)),
            "labelled_fact_accuracy_pct": _pct(labelled_matches, labelled_total),
            "all_fact_agreement_pct": _pct(tally["all_matches"], tally["all_total"]),
            "per_fact_accuracy_pct": {name: _pct(c["matches"], c["total"]) for name, c in sorted(tally["per_fact"].items())},
            "code_understanding_confusion": dict(sorted(tally["confusion"].items())),
            "classifier_fallbacks": len(results) - total,
            "classifier_calls": len(cases),
            "seconds": round(time.perf_counter() - started, 1),
            "unknown_transitions": tally["unknown"],
            "safety_violations": safety_violations,
            "downward_level_discrepancies": downward_levels,
            "downward_level_discrepancy_pct": _pct(downward_levels, total),
            "downward_tier_discrepancies": downward_tiers,
            "inspect_misclassifications": inspect_misclassifications,
            "unknown_facts_count": total_unknowns,
            "unknown_facts_pct": _pct(total_unknowns, total_facts),
            "by_provider": by_provider,
            **direction,
        },
        "cases": results,
    }


def print_report(data: dict) -> None:
    summary = data["summary"]
    print("=" * 80)
    print(" MODEL EFFORT ROUTER - PERFORMANCE & ACCURACY BENCHMARK REPORT")
    print("=" * 80)
    print(f" Total Benchmark Scenarios : {summary['total_benchmark_cases']}")
    print(f" Rule Match Accuracy       : {summary['accuracy_pct']}% ({summary['passed_cases']}/{summary['total_benchmark_cases']})")
    print(f" Safety Floor Compliance   : {summary['safety_guardrail_compliance_pct']}%")
    print(f" Rule Engine Throughput    : {summary['throughput_ops_sec']:,.0f} ops/sec")
    print(f" Latency (Mean)            : {summary['latency_us_mean']:.2f} µs ({summary['latency_us_mean']/1000:.4f} ms)")
    print(f" Latency (p50 Median)      : {summary['latency_us_p50']:.2f} µs")
    print(f" Latency (p95)             : {summary['latency_us_p95']:.2f} µs")
    print(f" Latency (p99)             : {summary['latency_us_p99']:.2f} µs")
    print("-" * 80)
    print(f"{'Case Name':<35} | {'Level':<8} | {'Tier':<9} | {'Ctx':<5} | {'Status':<6} | {'Latency'}")
    print("-" * 80)
    for c in data["cases"]:
        status = "PASS" if c["passed"] else "FAIL"
        ctx = "ASK" if c["unresolved"] else "no"
        print(f"{c['name']:<35} | {c['level']:<8} | {c['risk_tier']:<9} | {ctx:<5} | {status:<6} | {c['latency_us']} µs")
    classifier_data = data.get("classifier_benchmark")
    if classifier_data:
        classifier_summary = classifier_data["summary"]
        transitions = classifier_summary["unknown_transitions"]
        print("-" * 80)
        print(f" Live Classifier ({classifier_summary['platform']}): {classifier_summary['routing_accuracy_pct']}% routing, "
              f"{classifier_summary['labelled_fact_accuracy_pct']}% labelled facts "
              f"({classifier_summary['passed_cases']}/{classifier_summary['graded_cases']} graded), "
              f"task_type {classifier_summary['task_type_accuracy_pct']}%")
        print(f" Routing on fully-labelled cases: {classifier_summary['routing_accuracy_on_fully_labelled_pct']}% "
              f"({classifier_summary['fully_labelled_cases']}/{classifier_summary['graded_cases']} cases have every routing fact decided)")
        print(f" Model+effort profile match: {classifier_summary['profile_accuracy_pct']}%"
              f"{'' if classifier_summary['refinement_coverage'] else ' (no refinements on this platform: not informative)'}, "
              f"classifier fallbacks: {classifier_summary['classifier_fallbacks']}, "
              f"calls: {classifier_summary['classifier_calls']}, {classifier_summary['seconds']}s")
        print(f" Safety: {classifier_summary.get('safety_violations', 0)} violations, "
              f"downward level {classifier_summary.get('downward_level_discrepancy_pct', 0.0)}%, "
              f"downward tier {classifier_summary.get('downward_tier_discrepancies', 0)}, "
              f"inspect misclassifications: {classifier_summary.get('inspect_misclassifications', 0)}")
        print(f" Unknown facts: {classifier_summary.get('unknown_facts_pct', 0.0)}% "
              f"({classifier_summary.get('unknown_facts_count', 0)} total)")
        print(f" Unresolved (ASK) agreement: {classifier_summary.get('unresolved_matched_cases', 0)}/"
              f"{classifier_summary.get('unresolved_applicable_cases', 0)} applicable cases matched; "
              f"noul labelled unknowns unrepresentable on this path: "
              f"{classifier_summary.get('noul_unknown_unrepresentable_facts', 0)} fact(s) in "
              f"{classifier_summary.get('noul_unknown_unrepresentable_cases', 0)} case(s); "
              f"strict routing (counts them as misses): {classifier_summary.get('routing_accuracy_strict_pct', 0.0)}%")
        print(f" Level accuracy: {classifier_summary.get('level_accuracy_pct', 0.0)}%, "
              f"tier accuracy: {classifier_summary.get('tier_accuracy_pct', 0.0)}%, "
              f"±1 level: {classifier_summary.get('level_plus_minus_1_accuracy_pct', 0.0)}%")
        print(f" Failure split: over-route {classifier_summary.get('over_route_count', 0)} "
              f"({classifier_summary.get('over_route_pct', 0.0)}%), "
              f"under-route {classifier_summary.get('under_route_count', 0)}, "
              f"tier-only {classifier_summary.get('tier_only_mismatch_count', 0)}; "
              f"mean signed distance {classifier_summary.get('mean_signed_level_distance', 0.0)}, "
              f"mean over distance {classifier_summary.get('mean_over_route_distance', 0.0)}, "
              f"max over {classifier_summary.get('max_over_route_distance', 0)}")
        print(f" Tier recall: critical {classifier_summary.get('critical_recall_pct', 0.0)}% "
              f"({ '/'.join(map(str, classifier_summary.get('critical_recall_counts', [0, 0])))}), "
              f"elevated {classifier_summary.get('elevated_recall_pct', 0.0)}% "
              f"({ '/'.join(map(str, classifier_summary.get('elevated_recall_counts', [0, 0])))})")
        print(f" Cost (proxy L1=1 L2=2 L3=4 L4=8 L5=16 x tier): expected {classifier_summary.get('expected_cost', 0.0)}, "
              f"actual {classifier_summary.get('actual_cost', 0.0)}, "
              f"inflation x{classifier_summary.get('cost_inflation', 0.0)}")
        if classifier_summary.get("promoting_rule_counts"):
            top = list(classifier_summary["promoting_rule_counts"].items())[:5]
            print(" Top promoting rules: " + ", ".join(f"{k} x{v}" for k, v in top))
        if classifier_summary.get("fact_fp_counts"):
            print(f" Fact FP: {classifier_summary['fact_fp_counts']}")
        if classifier_summary.get("by_provider"):
            for prov, pstats in classifier_summary["by_provider"].items():
                print(f"  [{prov}] {pstats['routing_accuracy_pct']}% routing ({pstats['passed_cases']}/{pstats['graded_cases']}), "
                      f"safety violations: {pstats['safety_violations']}, unknown: {pstats['unknown_facts_pct']}%")
        print(f" requires_code_understanding (expected->actual): {classifier_summary['code_understanding_confusion'] or 'no labelled cases'}")
        print(" Unknown transitions: "
              f"expected→unknown={transitions['expected_unknown_to_unknown']}, "
              f"expected→known={transitions['expected_unknown_to_known']}, "
              f"known→unknown={transitions['expected_known_to_unknown']}")
    print("=" * 80)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate Model Effort Router performance and accuracy.")
    parser.add_argument("--json", action="store_true", help="Output raw JSON results")
    parser.add_argument("--live-classifier", action="store_true", help="Call the real classifier and compare its facts and route to the labelled corpus")
    parser.add_argument("--platform", choices=("codex", "claude-code", "antigravity"), default="codex", help="Classifier platform for --live-classifier")
    parser.add_argument("--limit", type=int, help="Limit live cases (useful for a low-cost sample)")
    parser.add_argument("--case", action="append", dest="case_names", help="Run one named live benchmark case; repeat to select more")
    args = parser.parse_args(argv or sys.argv[1:])
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if args.limit is not None and args.case_names:
        parser.error("--limit and --case cannot be combined")
    known = {case.name for case in GOLDEN_BENCHMARK_CASES}
    if unknown := sorted(set(args.case_names or ()) - known):
        parser.error(f"unknown --case: {', '.join(unknown)}")

    benchmark_data = evaluate_rules_benchmark()
    if args.live_classifier:
        calls = len(args.case_names or GOLDEN_BENCHMARK_CASES[: args.limit])
        print(f"Running {calls} live classifier calls on {args.platform} (this spends model usage)...", file=sys.stderr)
        benchmark_data["classifier_benchmark"] = evaluate_classifier_benchmark(args.platform, limit=args.limit, case_names=tuple(args.case_names or ()))
    if args.json:
        print(json.dumps(benchmark_data, indent=2, ensure_ascii=False))
    else:
        print_report(benchmark_data)

    rules_ok = benchmark_data["summary"]["accuracy_pct"] == 100.0
    if not args.live_classifier:
        return 0 if rules_ok else 1
    summary = benchmark_data["classifier_benchmark"]["summary"]
    if summary["classifier_fallbacks"]:
        print(f"FAIL: {summary['classifier_fallbacks']} classifier call(s) fell back; the classifier was unavailable, so accuracy is not reported as a result", file=sys.stderr)
        return 1
    profile_ok = summary["profile_accuracy_pct"] == 100.0 or not summary["refinement_coverage"]
    return 0 if rules_ok and summary["routing_accuracy_pct"] == 100.0 and profile_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

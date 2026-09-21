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


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    task: str
    task_type: str
    facts: dict[str, str]
    expected_level: str
    expected_tier: str = "standard"
    expected_risk_flags: tuple[str, ...] = ()
    expected_unresolved: tuple[str, ...] = ()


GOLDEN_BENCHMARK_CASES: list[BenchmarkCase] = [
    # L1 Cases (mechanical_only = yes, files_touched <= 1)
    BenchmarkCase(
        name="L1_doc_typo_fix",
        task="Fix documentation typo in README.md",
        task_type="implementation",
        facts={"mechanical_only": "yes", "files_touched": "1", "fix_or_result_known": "yes"},
        expected_level="L1",
    ),
    BenchmarkCase(
        name="L1_unused_import_cleanup",
        task="Remove unused imports in main.py",
        task_type="local_refactoring",
        facts={"mechanical_only": "yes", "files_touched": "1", "fix_or_result_known": "yes"},
        expected_level="L1",
    ),
    BenchmarkCase(
        name="L1_code_formatting",
        task="Run code formatter and fix whitespace styling in single module",
        task_type="local_refactoring",
        facts={"mechanical_only": "yes", "files_touched": "1", "fix_or_result_known": "yes"},
        expected_level="L1",
    ),
    BenchmarkCase(
        name="L1_rename_local_variable",
        task="Rename local variable foo to bar in helper function",
        task_type="local_refactoring",
        facts={"mechanical_only": "yes", "files_touched": "1", "fix_or_result_known": "yes"},
        expected_level="L1",
    ),

    # L2 Cases (base level, 1 file touched, clear fix)
    BenchmarkCase(
        name="L2_simple_bug_fix",
        task="Fix off-by-one error in pagination calculation in view.py",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "1", "fix_or_result_known": "yes", "requires_code_understanding": "yes"},
        expected_level="L2",
    ),
    BenchmarkCase(
        name="L2_single_file_helper",
        task="Add helper function to parse date string in utils.py",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "1", "fix_or_result_known": "yes", "requires_code_understanding": "no"},
        expected_level="L2",
    ),
    BenchmarkCase(
        name="L2_review_small_pr",
        task="Review 5-line PR fixing a typo and null check",
        task_type="review",
        facts={"mechanical_only": "no", "files_touched": "0", "fix_or_result_known": "yes"},
        expected_level="L2",
    ),
    BenchmarkCase(
        name="L2_local_extract_function",
        task="Extract duplicate validation logic into a local function in validator.py",
        task_type="local_refactoring",
        facts={"mechanical_only": "no", "files_touched": "1", "fix_or_result_known": "yes", "requires_code_understanding": "yes"},
        expected_level="L2",
    ),

    # L2 implementer rung: requires_code_understanding picks Luna high / Sonnet low over Luna medium / Haiku.
    # yes = the edit is only right after reading existing code; no = self-contained and evident from the text.
    BenchmarkCase(
        name="L2U_pattern_following_validation",
        task="Add input validation to create_user in api/users.py, following how create_order in api/orders.py validates its input",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "1", "fix_or_result_known": "yes", "requires_code_understanding": "yes"},
        expected_level="L2",
    ),
    BenchmarkCase(
        name="L2U_fix_after_reading_call_sites",
        task="Fix the off-by-one in paginate() in utils.py, but first check how its callers pass the page index so the fix does not break them",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "1", "fix_or_result_known": "yes", "requires_code_understanding": "yes"},
        expected_level="L2",
    ),
    BenchmarkCase(
        name="L2U_match_existing_retry_semantics",
        task="In report.py, make the error branch of fetch_report() use the same error set that the existing _is_transient() helper in that file already checks",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "1", "fix_or_result_known": "yes", "requires_code_understanding": "yes"},
        expected_level="L2",
    ),
    BenchmarkCase(
        name="L2U_add_optional_field",
        task="Add an optional nickname string field with default None to the User dataclass in dto.py",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "1", "fix_or_result_known": "yes", "requires_code_understanding": "no"},
        expected_level="L2",
    ),
    BenchmarkCase(
        name="L2U_standalone_helper",
        task="Add a standalone function clamp(value, low, high) that returns value limited to the range, to utils.py",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "1", "fix_or_result_known": "yes", "requires_code_understanding": "no"},
        expected_level="L2",
    ),
    BenchmarkCase(
        name="L2U_test_for_stated_behaviour",
        task="Add a unit test in tests/test_math.py asserting that add(2, 3) returns 5",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "1", "fix_or_result_known": "yes", "requires_code_understanding": "no"},
        expected_level="L2",
    ),

    # L3 Cases (files_touched 2-5 or unknown fix/result)
    BenchmarkCase(
        name="L3_multifile_feature",
        task="Implement user profile avatar upload across controller, service, and template",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "2-5", "fix_or_result_known": "yes"},
        expected_level="L3",
    ),
    BenchmarkCase(
        name="L3_open_ended_investigation",
        task="Investigate why some background tasks finish slowly in worker pool",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "1", "fix_or_result_known": "no"},
        expected_level="L3",
    ),
    BenchmarkCase(
        name="L3_unit_tests_addition",
        task="Add unit test suite covering user authentication helper utilities",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "2-5", "fix_or_result_known": "yes"},
        expected_level="L3",
    ),
    BenchmarkCase(
        name="L3_local_refactor_three_files",
        task="Refactor string parsing utils across 3 related test files",
        task_type="local_refactoring",
        facts={"mechanical_only": "no", "files_touched": "2-5", "fix_or_result_known": "yes"},
        expected_level="L3",
    ),

    # L4 Cases (crosses_module_boundary, public_api_change, data_migration, files_touched 6+)
    BenchmarkCase(
        name="L4_cross_module_refactor",
        task="Move billing helpers from core module to billing module and update call sites",
        task_type="architectural_refactoring",
        facts={"mechanical_only": "no", "files_touched": "6+", "crosses_module_boundary": "yes", "fix_or_result_known": "yes"},
        expected_level="L4",
    ),
    BenchmarkCase(
        name="L4_public_api_change",
        task="Change REST API response envelope from data/error to standard RFC7807 problem details",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "2-5", "changes_public_api_contract": "yes", "fix_or_result_known": "yes"},
        expected_level="L4",
        expected_risk_flags=("public_api_change",),
    ),
    BenchmarkCase(
        name="L4_db_data_migration",
        task="Add database migration script to split users full_name into first_name and last_name",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "2-5", "changes_persisted_data": "yes", "fix_or_result_known": "yes"},
        expected_level="L4",
        expected_risk_flags=("data_migration",),
    ),
    BenchmarkCase(
        name="L4_large_scale_files_change",
        task="Update deprecated logger calls across 15 files in backend",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "6+", "fix_or_result_known": "yes"},
        expected_level="L4",
    ),
    BenchmarkCase(
        # An unknown fact never floors the level: it is reported as unresolved (a question for
        # the user), and the level comes from the explicit facts (files_touched=2-5 gives L3).
        name="L3_unknown_module_boundary_unresolved",
        task="Refactor session handling where module boundary impact is unknown",
        task_type="architectural_refactoring",
        facts={"mechanical_only": "no", "files_touched": "2-5", "crosses_module_boundary": "unknown"},
        expected_level="L3",
        expected_unresolved=("crosses_module_boundary",),
    ),

    BenchmarkCase(
        name="L2_unknown_security_change_is_not_a_floor",
        task="Fix the login problem",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "1", "changes_security_or_payment_logic": "unknown"},
        expected_level="L2",
        expected_unresolved=("changes_security_or_payment_logic",),
    ),

    # L5 Cases (needs_new_structure, intermittent_or_concurrency, open result across modules)
    BenchmarkCase(
        name="L5_new_plugin_architecture",
        task="Design and implement new dynamic plugin loading architecture with isolated contexts",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "6+", "needs_new_structure": "yes", "fix_or_result_known": "yes"},
        expected_level="L5",
    ),
    BenchmarkCase(
        name="L5_concurrency_race_condition",
        task="Fix intermittent race condition causing deadlocks in thread pool queue",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "2-5", "intermittent_or_concurrency": "yes", "fix_or_result_known": "no"},
        expected_level="L5",
    ),
    BenchmarkCase(
        name="L5_open_result_across_modules",
        task="Diagnose mysterious memory leak spanning cache module and worker daemon",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "2-5", "fix_or_result_known": "no", "crosses_module_boundary": "yes"},
        expected_level="L5",
    ),
    BenchmarkCase(
        name="L5_architectural_design",
        task="Design architecture for migrating from monolithic event bus to distributed messaging",
        task_type="design",
        facts={"mechanical_only": "no", "files_touched": "0", "needs_new_structure": "yes", "fix_or_result_known": "yes"},
        expected_level="L5",
    ),

    # Elevated-tier cases (changes_security_or_payment_logic, intermittent across services)
    BenchmarkCase(
        name="L5E_security_oauth_token_refresh",
        task="Revamp OAuth 2.0 refresh token rotation and JWT signature validation",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "2-5", "changes_security_or_payment_logic": "yes", "fix_or_result_known": "yes"},
        expected_level="L5",
        expected_tier="elevated",
        expected_risk_flags=("security_sensitive", "authentication"),
    ),
    BenchmarkCase(
        name="L5E_payment_stripe_integration",
        task="Implement Stripe webhook signature verification and checkout session payment handler",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "2-5", "changes_security_or_payment_logic": "yes", "fix_or_result_known": "yes"},
        expected_level="L5",
        expected_tier="elevated",
        expected_risk_flags=("security_sensitive", "payment"),
    ),
    BenchmarkCase(
        name="L5E_security_rbac_authorization",
        task="Update role-based access control (RBAC) permission check middleware",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "2-5", "changes_security_or_payment_logic": "yes", "fix_or_result_known": "yes"},
        expected_level="L5",
        expected_tier="elevated",
        expected_risk_flags=("security_sensitive", "authorization"),
    ),
    BenchmarkCase(
        name="L5E_cross_service_intermittent_bug",
        task="Investigate intermittent distributed transaction failure across auth and order microservices",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "6+", "intermittent_or_concurrency": "yes", "crosses_service_boundary": "yes"},
        expected_level="L5",
        expected_tier="elevated",
    ),

    # MEDIUM-A regression: the approval-gate carve-out must stay narrow. A
    # cost/model-tier confirmation (approving an expensive model before it runs)
    # is workflow control, not permissions, and must not float to a security
    # floor. Removing the equivalent gate on a real access-control boundary
    # (a prod deploy approval bypass) is the opposite: that IS permissions.
    BenchmarkCase(
        name="L2_model_tier_approval_confirmation",
        task="Add a confirmation prompt before running an expensive high-tier model, gated behind a --yes flag",
        task_type="implementation",
        facts={
            "mechanical_only": "no",
            "files_touched": "1",
            "fix_or_result_known": "yes",
            "changes_security_or_payment_logic": "no",
            "reviews_security_sensitive_code": "no",
            "security_domain": "none",
            "requires_code_understanding": "yes",
        },
        expected_level="L2",
    ),
    BenchmarkCase(
        name="L5E_deploy_approval_bypass_removed",
        task="Remove the --approved bypass on the production deploy approval gate so deploys can no longer skip user consent",
        task_type="implementation",
        facts={
            "mechanical_only": "no",
            "files_touched": "1",
            "fix_or_result_known": "yes",
            "changes_security_or_payment_logic": "yes",
            "reviews_security_sensitive_code": "yes",
            "security_domain": "permissions",
        },
        expected_level="L5",
        expected_tier="elevated",
        expected_risk_flags=("security_sensitive",),
    ),

    # Elevated-tier cases (needs_new_structure + crosses_service_boundary + fix_or_result_known=no)
    BenchmarkCase(
        # Cross-service open design with silent material harm: the elevated tier.
        name="L5E_multi_service_frontier_redesign",
        task="Solve chronic cross-service data inconsistency with unknown root cause requiring new cross-repo protocol",
        task_type="architectural_refactoring",
        facts={"mechanical_only": "no", "files_touched": "6+", "needs_new_structure": "yes", "crosses_service_boundary": "yes", "fix_or_result_known": "no", "silent_failure_material_harm": "yes"},
        expected_level="L5",
        expected_tier="elevated",
    ),
    BenchmarkCase(
        # A novel consensus protocol across multi-region sync: cross-service open design, elevated tier.
        name="L5E_distributed_consensus_design",
        task="Design novel distributed consensus protocol replacing legacy multi-region sync mechanism",
        task_type="design",
        facts={"mechanical_only": "no", "files_touched": "0", "needs_new_structure": "yes", "crosses_service_boundary": "yes", "fix_or_result_known": "no", "blast_radius": "broad"},
        expected_level="L5",
        expected_tier="elevated",
    ),

    # Critical-tier cases (irreversible_or_ledger_or_crypto = yes)
    BenchmarkCase(
        name="L5C_ledger_balance_reconciliation",
        task="Implement double-entry financial ledger balance settlement and invariant verification",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "2-5", "irreversible_or_ledger_or_crypto": "yes", "fix_or_result_known": "yes"},
        expected_level="L5",
        expected_tier="critical",
    ),
    BenchmarkCase(
        name="L5C_crypto_key_derivation",
        task="Design cryptographic key derivation and zero-knowledge proof verification pipeline",
        task_type="design",
        facts={"mechanical_only": "no", "files_touched": "0", "irreversible_or_ledger_or_crypto": "yes", "needs_new_structure": "yes"},
        expected_level="L5",
        expected_tier="critical",
    ),
    BenchmarkCase(
        name="L5C_irreversible_database_purge",
        task="Execute irreversible GDPR permanent data erasure on production partition tables",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "1", "irreversible_or_ledger_or_crypto": "yes", "changes_persisted_data": "yes"},
        expected_level="L5",
        expected_tier="critical",
    ),
]


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


def _grade_case(case: BenchmarkCase, actual: router.Classification, config: dict, platform: str, base_facts: dict[str, str]) -> dict:
    """Grade one classifier answer against its labels: fact agreement, level/tier, and the routed model+effort."""
    expected_facts = {**base_facts, **case.facts}
    # Only labelled facts are graded: a fact the case does not label follows the classifier's own answer, so the
    # corpus default ("nothing risky here") cannot fail routing or the profile for a fact nobody labelled.
    graded_facts = {
        **expected_facts,
        **{name: value for name, value in actual.facts.items() if value is not None and name not in case.facts},
    }
    expected_level, expected_tier, _, expected_unresolved = router.evaluate_rules(graded_facts)
    per_fact = {name: {"expected": expected, "actual": actual.facts.get(name)} for name, expected in expected_facts.items()}
    # task_type is graded on its own: implementation and local_refactoring route identically, so a swap must not fail routing.
    routing_match = (
        actual.level == expected_level
        and actual.risk_tier == expected_tier
        and actual.unresolved == expected_unresolved
    )
    expected_classification = router.Classification(
        task_type=case.task_type, level=expected_level, risk_flags=router.risk_flags_from_facts(graded_facts),
        reason="labelled", source="test", facts=graded_facts, risk_tier=expected_tier,
    )
    expected_profile = _route_profile(config, platform, case.task, expected_classification, expected_tier == "critical")
    actual_profile = _route_profile(config, platform, case.task, actual, actual.risk_tier == "critical")
    return {
        "name": case.name,
        "source": actual.source,
        "graded": True,
        "passed": routing_match,
        "task_type_passed": actual.task_type == case.task_type,
        # A routing error on both sides is a broken config, never a match.
        "profile_passed": "error" not in actual_profile and expected_profile == actual_profile,
        "expected": {
            "task_type": case.task_type, "level": expected_level, "risk_tier": expected_tier,
            "unresolved": list(expected_unresolved), "profile": expected_profile,
        },
        "actual": {
            "task_type": actual.task_type, "level": actual.level, "risk_tier": actual.risk_tier,
            "unresolved": list(actual.unresolved), "profile": actual_profile,
        },
        "facts": per_fact,
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
    return {
        "summary": {
            "platform": platform,
            "total_benchmark_cases": len(cases),
            "graded_cases": total,
            "passed_cases": sum(item["passed"] for item in graded_cases),
            "routing_accuracy_pct": _pct(sum(item["passed"] for item in graded_cases), total),
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
        print(f" Model+effort profile match: {classifier_summary['profile_accuracy_pct']}%"
              f"{'' if classifier_summary['refinement_coverage'] else ' (no refinements on this platform: not informative)'}, "
              f"classifier fallbacks: {classifier_summary['classifier_fallbacks']}, "
              f"calls: {classifier_summary['classifier_calls']}, {classifier_summary['seconds']}s")
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

#!/usr/bin/env python3
"""Comprehensive performance and accuracy evaluation benchmark for Model Effort Router."""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import sys
import time
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
    expected_critical: bool = False
    expected_risk_flags: tuple[str, ...] = ()
    expected_needs_context: bool = False


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
        facts={"mechanical_only": "no", "files_touched": "1", "fix_or_result_known": "yes"},
        expected_level="L2",
    ),
    BenchmarkCase(
        name="L2_single_file_helper",
        task="Add helper function to parse date string in utils.py",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "1", "fix_or_result_known": "yes"},
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
        facts={"mechanical_only": "no", "files_touched": "1", "fix_or_result_known": "yes"},
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
        # crosses_module_boundary unknown is a context-only signal (asks for repo
        # context) and no longer floors the level itself, so this settles at L3
        # from files_touched=2-5 rather than the old L4 floor.
        name="L3_unknown_module_boundary_needs_context",
        task="Refactor session handling where module boundary impact is unknown",
        task_type="architectural_refactoring",
        facts={"mechanical_only": "no", "files_touched": "2-5", "crosses_module_boundary": "unknown"},
        expected_level="L3",
        expected_needs_context=True,
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

    # L6 Cases (changes_security_or_payment_logic, intermittent across services)
    BenchmarkCase(
        name="L6_security_oauth_token_refresh",
        task="Revamp OAuth 2.0 refresh token rotation and JWT signature validation",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "2-5", "changes_security_or_payment_logic": "yes", "fix_or_result_known": "yes"},
        expected_level="L6",
        expected_risk_flags=("security_sensitive", "authentication"),
    ),
    BenchmarkCase(
        name="L6_payment_stripe_integration",
        task="Implement Stripe webhook signature verification and checkout session payment handler",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "2-5", "changes_security_or_payment_logic": "yes", "fix_or_result_known": "yes"},
        expected_level="L6",
        expected_risk_flags=("security_sensitive", "payment"),
    ),
    BenchmarkCase(
        name="L6_security_rbac_authorization",
        task="Update role-based access control (RBAC) permission check middleware",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "2-5", "changes_security_or_payment_logic": "yes", "fix_or_result_known": "yes"},
        expected_level="L6",
        expected_risk_flags=("security_sensitive", "authorization"),
    ),
    BenchmarkCase(
        name="L6_cross_service_intermittent_bug",
        task="Investigate intermittent distributed transaction failure across auth and order microservices",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "6+", "intermittent_or_concurrency": "yes", "crosses_service_boundary": "yes"},
        expected_level="L6",
    ),

    # MEDIUM-A regression: the approval-gate carve-out must stay narrow. A
    # cost/model-tier confirmation (this router's own Fable/Astra approval gate)
    # is workflow control, not permissions, and must not float to a security
    # floor. Removing the equivalent gate on a real access-control boundary
    # (a prod deploy approval bypass) is the opposite: that IS permissions.
    BenchmarkCase(
        name="L2_model_tier_approval_confirmation",
        task="Add a confirmation prompt before running the router's Fable/Astra high-tier model, gated behind --approved",
        task_type="implementation",
        facts={
            "mechanical_only": "no",
            "files_touched": "1",
            "fix_or_result_known": "yes",
            "changes_security_or_payment_logic": "no",
            "reviews_security_sensitive_code": "no",
            "security_domain": "none",
        },
        expected_level="L2",
    ),
    BenchmarkCase(
        name="L6_deploy_approval_bypass_removed",
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
        expected_level="L6",
        expected_risk_flags=("security_sensitive",),
    ),

    # L7 Cases (needs_new_structure + crosses_service_boundary + fix_or_result_known=no)
    BenchmarkCase(
        # Old policy: cross-service open design alone was L7. New policy: that
        # combination alone is L6; L7 needs blast_radius broad or silent
        # material harm on top. This task's "chronic cross-service data
        # inconsistency" is the silent_failure_material_harm example verbatim,
        # so the fact is set explicitly rather than lowering the expectation.
        name="L7_multi_service_frontier_redesign",
        task="Solve chronic cross-service data inconsistency with unknown root cause requiring new cross-repo protocol",
        task_type="architectural_refactoring",
        facts={"mechanical_only": "no", "files_touched": "6+", "needs_new_structure": "yes", "crosses_service_boundary": "yes", "fix_or_result_known": "no", "silent_failure_material_harm": "yes"},
        expected_level="L7",
    ),
    BenchmarkCase(
        # Same L7 policy change as above. A novel consensus protocol across
        # multi-region sync affects many services/regions system-wide, so
        # blast_radius broad is made explicit rather than lowering to L6.
        name="L7_distributed_consensus_design",
        task="Design novel distributed consensus protocol replacing legacy multi-region sync mechanism",
        task_type="design",
        facts={"mechanical_only": "no", "files_touched": "0", "needs_new_structure": "yes", "crosses_service_boundary": "yes", "fix_or_result_known": "no", "blast_radius": "broad"},
        expected_level="L7",
    ),

    # Critical Override Cases (irreversible_or_ledger_or_crypto = yes)
    BenchmarkCase(
        name="Critical_ledger_balance_reconciliation",
        task="Implement double-entry financial ledger balance settlement and invariant verification",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "2-5", "irreversible_or_ledger_or_crypto": "yes", "fix_or_result_known": "yes"},
        expected_level="L7",
        expected_critical=True,
    ),
    BenchmarkCase(
        name="Critical_crypto_key_derivation",
        task="Design cryptographic key derivation and zero-knowledge proof verification pipeline",
        task_type="design",
        facts={"mechanical_only": "no", "files_touched": "0", "irreversible_or_ledger_or_crypto": "yes", "needs_new_structure": "yes"},
        expected_level="L7",
        expected_critical=True,
    ),
    BenchmarkCase(
        name="Critical_irreversible_database_purge",
        task="Execute irreversible GDPR permanent data erasure on production partition tables",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "1", "irreversible_or_ledger_or_crypto": "yes", "changes_persisted_data": "yes"},
        expected_level="L7",
        expected_critical=True,
    ),
]


_FACT_DEFAULT_OVERRIDES = {
    "fix_or_result_known": "yes",
    "files_touched": "1",
    "security_domain": "none",
    "blast_radius": "narrow",
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
        level, critical, matched_rules, needs_context = router.evaluate_rules(merged_facts)
        t_elapsed_us = (time.perf_counter_ns() - t0) / 1000.0
        latencies_us.append(t_elapsed_us)

        # Accuracy check
        critical_match = (critical == case.expected_critical)
        context_match = (needs_context == case.expected_needs_context)
        if case.expected_critical:
            level_match = critical_match
        else:
            level_match = (level == case.expected_level)
        passed = level_match and critical_match and context_match
        if passed:
            accuracy_passes += 1

        # Safety floor checks
        has_security = merged_facts.get("changes_security_or_payment_logic") == "yes"
        if has_security and router.LEVELS.index(level) < router.LEVELS.index("L6") and not critical:
            safety_violations += 1

        has_api_or_migration = (
            merged_facts.get("changes_public_api_contract") == "yes"
            or merged_facts.get("changes_persisted_data") == "yes"
        )
        if has_api_or_migration and router.LEVELS.index(level) < router.LEVELS.index("L4") and not critical:
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
            )
            route_res = router.route(
                case.task,
                plat,
                config,
                classifier=lambda _t, c=mock_classification: c,
                critical=critical,
            )
            platform_routes[plat] = {
                "level": route_res.level,
                "stages": [s["model"] for s in route_res.stages],
                "mode": route_res.mode,
            }

        results.append({
            "name": case.name,
            "passed": passed,
            "level": level,
            "critical": critical,
            "matched_rules": matched_rules,
            "needs_context": needs_context,
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
    print(f"{'Case Name':<35} | {'Level':<8} | {'Crit':<5} | {'Ctx':<5} | {'Status':<6} | {'Latency'}")
    print("-" * 80)
    for c in data["cases"]:
        status = "PASS" if c["passed"] else "FAIL"
        crit = "YES" if c["critical"] else "no"
        ctx = "YES" if c["needs_context"] else "no"
        print(f"{c['name']:<35} | {c['level']:<8} | {crit:<5} | {ctx:<5} | {status:<6} | {c['latency_us']} µs")
    print("=" * 80)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate Model Effort Router performance and accuracy.")
    parser.add_argument("--json", action="store_true", help="Output raw JSON results")
    args = parser.parse_args(argv or sys.argv[1:])

    benchmark_data = evaluate_rules_benchmark()
    if args.json:
        print(json.dumps(benchmark_data, indent=2, ensure_ascii=False))
    else:
        print_report(benchmark_data)

    return 0 if benchmark_data["summary"]["accuracy_pct"] == 100.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Golden benchmark cases for Level 3."""

from __future__ import annotations

from benchmark_cases.models import BenchmarkCase

CASES_L3: list[BenchmarkCase] = [
    # =========================================================================
    # L3 Cases (files_touched 2-5 or unknown fix/result) - Total 20
    # =========================================================================
    BenchmarkCase(
        name="L3_open_ended_investigation",
        task="Investigate why some background tasks finish slowly in worker pool",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "unknown", "crosses_module_boundary": "no", "crosses_service_boundary": "no", "fix_or_result_known": "no", "intermittent_or_concurrency": "no", "needs_new_structure": "no", "changes_security_or_payment_logic": "no", "reviews_security_sensitive_code": "no", "security_domain": "none", "changes_public_api_contract": "no", "changes_persisted_data": "no", "irreversible_or_ledger_or_crypto": "no", "changes_trust_boundary": "no", "blast_radius": "narrow", "silent_failure_material_harm": "no", "requires_code_understanding": "yes"},
        expected_level="L3",
        expected_unresolved=("files_touched",),
    ),
    BenchmarkCase(
        name="L3_local_refactor_three_files",
        task="Refactor string parsing utils across 3 related test files",
        task_type="local_refactoring",
        facts={"mechanical_only": "no", "files_touched": "2-5", "crosses_module_boundary": "no", "crosses_service_boundary": "no", "fix_or_result_known": "yes", "intermittent_or_concurrency": "no", "needs_new_structure": "no", "changes_security_or_payment_logic": "no", "reviews_security_sensitive_code": "no", "security_domain": "none", "changes_public_api_contract": "no", "changes_persisted_data": "no", "irreversible_or_ledger_or_crypto": "no", "changes_trust_boundary": "no", "blast_radius": "narrow", "silent_failure_material_harm": "no", "requires_code_understanding": "yes"},
        expected_level="L3",
    ),
    BenchmarkCase(
        name="L3_sync_enum_two_files",
        task="Sync status enum values between models/status.py and serializers/status.py",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "2-5", "crosses_module_boundary": "no", "crosses_service_boundary": "no", "fix_or_result_known": "yes", "intermittent_or_concurrency": "no", "needs_new_structure": "no", "changes_security_or_payment_logic": "no", "reviews_security_sensitive_code": "no", "security_domain": "none", "changes_public_api_contract": "no", "changes_persisted_data": "no", "irreversible_or_ledger_or_crypto": "no", "changes_trust_boundary": "no", "blast_radius": "narrow", "silent_failure_material_harm": "no", "requires_code_understanding": "yes"},
        expected_level="L3",
    ),
    BenchmarkCase(
        name="L3_rename_function_four_files",
        task="Rename helper function calculate_discount across 4 checkout files",
        task_type="local_refactoring",
        facts={"mechanical_only": "no", "files_touched": "2-5", "crosses_module_boundary": "no", "crosses_service_boundary": "no", "fix_or_result_known": "yes", "intermittent_or_concurrency": "no", "needs_new_structure": "no", "changes_security_or_payment_logic": "no", "reviews_security_sensitive_code": "no", "security_domain": "none", "changes_public_api_contract": "no", "changes_persisted_data": "no", "irreversible_or_ledger_or_crypto": "no", "changes_trust_boundary": "no", "blast_radius": "narrow", "silent_failure_material_harm": "no", "requires_code_understanding": "yes"},
        expected_level="L3",
    ),
    # Label-policy tension, needs adjudication: policy counts "determining the amount charged
    # (price, discount, or tax calculation)" as payment, and promo-code validation decides whether
    # a discount applies, yet this case is labelled security_domain=none. It is inert for routing
    # (the route is already L5 through the security/payment FP), so the criteria were left alone;
    # revisit the policy or the label once a few more promo/pricing cases accumulate.
    BenchmarkCase(
        name="L3_add_feature_controller_service",
        task="Add promo code validation logic across cart_controller.py and promo_service.py",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "2-5", "crosses_module_boundary": "no", "crosses_service_boundary": "no", "fix_or_result_known": "yes", "intermittent_or_concurrency": "no", "needs_new_structure": "no", "changes_security_or_payment_logic": "no", "reviews_security_sensitive_code": "no", "security_domain": "none", "changes_public_api_contract": "no", "changes_persisted_data": "no", "irreversible_or_ledger_or_crypto": "no", "changes_trust_boundary": "no", "blast_radius": "narrow", "silent_failure_material_harm": "no", "requires_code_understanding": "yes"},
        expected_level="L3",
    ),
    BenchmarkCase(
        name="L3_unit_test_expansion_three_files",
        task="Add test coverage for email notification templates across 3 test files",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "2-5", "crosses_module_boundary": "no", "crosses_service_boundary": "no", "fix_or_result_known": "yes", "intermittent_or_concurrency": "no", "needs_new_structure": "no", "changes_security_or_payment_logic": "no", "reviews_security_sensitive_code": "no", "security_domain": "none", "changes_public_api_contract": "no", "changes_persisted_data": "no", "irreversible_or_ledger_or_crypto": "no", "changes_trust_boundary": "no", "blast_radius": "narrow", "silent_failure_material_harm": "no", "requires_code_understanding": "yes"},
        expected_level="L3",
    ),
    BenchmarkCase(
        name="L3_extract_shared_utility_three_files",
        task="Extract duplicate date formatting code across 3 parser modules into a shared helper",
        task_type="local_refactoring",
        facts={"mechanical_only": "no", "files_touched": "2-5", "crosses_module_boundary": "no", "crosses_service_boundary": "no", "fix_or_result_known": "yes", "intermittent_or_concurrency": "no", "needs_new_structure": "no", "changes_security_or_payment_logic": "no", "reviews_security_sensitive_code": "no", "security_domain": "none", "changes_public_api_contract": "no", "changes_persisted_data": "no", "irreversible_or_ledger_or_crypto": "no", "changes_trust_boundary": "no", "blast_radius": "narrow", "silent_failure_material_harm": "no", "requires_code_understanding": "yes"},
        expected_level="L3",
    ),
    BenchmarkCase(
        name="L3_update_fixtures_two_files",
        task="Update mock user session fixtures in test_client.py and test_billing.py",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "2-5", "crosses_module_boundary": "no", "crosses_service_boundary": "no", "fix_or_result_known": "yes", "intermittent_or_concurrency": "no", "needs_new_structure": "no", "changes_security_or_payment_logic": "no", "reviews_security_sensitive_code": "no", "security_domain": "none", "changes_public_api_contract": "no", "changes_persisted_data": "no", "irreversible_or_ledger_or_crypto": "no", "changes_trust_boundary": "no", "blast_radius": "narrow", "silent_failure_material_harm": "no", "requires_code_understanding": "yes"},
        expected_level="L3",
    ),
    BenchmarkCase(
        name="L3_cli_argument_two_files",
        task="Add --verbose flag support to cli/runner.py and cli/parser.py",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "2-5", "crosses_module_boundary": "no", "crosses_service_boundary": "no", "fix_or_result_known": "yes", "intermittent_or_concurrency": "no", "needs_new_structure": "no", "changes_security_or_payment_logic": "no", "reviews_security_sensitive_code": "no", "security_domain": "none", "changes_public_api_contract": "no", "changes_persisted_data": "no", "irreversible_or_ledger_or_crypto": "no", "changes_trust_boundary": "no", "blast_radius": "narrow", "silent_failure_material_harm": "no", "requires_code_understanding": "yes"},
        expected_level="L3",
    ),
    BenchmarkCase(
        name="L3_refactor_logger_four_files",
        task="Standardize structured logging format across 4 background worker handler files",
        task_type="local_refactoring",
        facts={"mechanical_only": "no", "files_touched": "2-5", "crosses_module_boundary": "no", "crosses_service_boundary": "no", "fix_or_result_known": "yes", "intermittent_or_concurrency": "no", "needs_new_structure": "no", "changes_security_or_payment_logic": "no", "reviews_security_sensitive_code": "no", "security_domain": "none", "changes_public_api_contract": "no", "changes_persisted_data": "no", "irreversible_or_ledger_or_crypto": "no", "changes_trust_boundary": "no", "blast_radius": "narrow", "silent_failure_material_harm": "no", "requires_code_understanding": "yes"},
        expected_level="L3",
    ),
    BenchmarkCase(
        name="L3_i18n_translation_three_files",
        task="Add Korean localization strings across 3 frontend template files",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "2-5", "crosses_module_boundary": "no", "crosses_service_boundary": "no", "fix_or_result_known": "yes", "intermittent_or_concurrency": "no", "needs_new_structure": "no", "changes_security_or_payment_logic": "no", "reviews_security_sensitive_code": "no", "security_domain": "none", "changes_public_api_contract": "no", "changes_persisted_data": "no", "irreversible_or_ledger_or_crypto": "no", "changes_trust_boundary": "no", "blast_radius": "narrow", "silent_failure_material_harm": "no", "requires_code_understanding": "yes"},
        expected_level="L3",
    ),
    BenchmarkCase(
        name="L3_batch_rename_constants_two_files",
        task="Rename deprecated HTTP status constants in routes.py and handlers.py",
        task_type="local_refactoring",
        facts={"mechanical_only": "no", "files_touched": "2-5", "crosses_module_boundary": "no", "crosses_service_boundary": "no", "fix_or_result_known": "yes", "intermittent_or_concurrency": "no", "needs_new_structure": "no", "changes_security_or_payment_logic": "no", "reviews_security_sensitive_code": "no", "security_domain": "none", "changes_public_api_contract": "no", "changes_persisted_data": "no", "irreversible_or_ledger_or_crypto": "no", "changes_trust_boundary": "no", "blast_radius": "narrow", "silent_failure_material_harm": "no", "requires_code_understanding": "yes"},
        expected_level="L3",
    ),
    BenchmarkCase(
        name="L3_investigate_test_flakiness",
        task="Investigate and fix why TestUserRegistration fails intermittently under local pytest",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "unknown", "crosses_module_boundary": "no", "crosses_service_boundary": "no", "fix_or_result_known": "no", "intermittent_or_concurrency": "no", "needs_new_structure": "no", "changes_security_or_payment_logic": "no", "reviews_security_sensitive_code": "no", "security_domain": "none", "changes_public_api_contract": "no", "changes_persisted_data": "no", "irreversible_or_ledger_or_crypto": "no", "changes_trust_boundary": "no", "blast_radius": "narrow", "silent_failure_material_harm": "no", "requires_code_understanding": "yes"},
        expected_level="L3",
        expected_unresolved=("files_touched",),
    ),
    BenchmarkCase(
        name="L3_debug_incorrect_tax_rounding",
        task="Find why tax rounding calculation produces a 1 cent difference on international invoices",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "unknown", "crosses_module_boundary": "no", "crosses_service_boundary": "no", "fix_or_result_known": "no", "intermittent_or_concurrency": "no", "needs_new_structure": "no", "changes_security_or_payment_logic": "no", "reviews_security_sensitive_code": "no", "security_domain": "none", "changes_public_api_contract": "no", "changes_persisted_data": "no", "irreversible_or_ledger_or_crypto": "no", "changes_trust_boundary": "no", "blast_radius": "narrow", "silent_failure_material_harm": "no", "requires_code_understanding": "yes"},
        expected_level="L3",
        expected_unresolved=("files_touched",),
    ),
    BenchmarkCase(
        name="L3_investigate_slow_query_plan",
        task="Determine why user profile search query plan stopped using the expected composite index",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "unknown", "crosses_module_boundary": "no", "crosses_service_boundary": "no", "fix_or_result_known": "no", "intermittent_or_concurrency": "no", "needs_new_structure": "no", "changes_security_or_payment_logic": "no", "reviews_security_sensitive_code": "no", "security_domain": "none", "changes_public_api_contract": "no", "changes_persisted_data": "no", "irreversible_or_ledger_or_crypto": "no", "changes_trust_boundary": "no", "blast_radius": "narrow", "silent_failure_material_harm": "no", "requires_code_understanding": "yes"},
        expected_level="L3",
        expected_unresolved=("files_touched",),
    ),
    BenchmarkCase(
        name="L3_diagnose_broken_pipeline_stage",
        task="Diagnose root cause of build artifact packaging failure in release pipeline",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "unknown", "crosses_module_boundary": "no", "crosses_service_boundary": "no", "fix_or_result_known": "no", "intermittent_or_concurrency": "no", "needs_new_structure": "no", "changes_security_or_payment_logic": "no", "reviews_security_sensitive_code": "no", "security_domain": "none", "changes_public_api_contract": "no", "changes_persisted_data": "no", "irreversible_or_ledger_or_crypto": "no", "changes_trust_boundary": "no", "blast_radius": "narrow", "silent_failure_material_harm": "no", "requires_code_understanding": "yes"},
        expected_level="L3",
        expected_unresolved=("files_touched",),
    ),
    BenchmarkCase(
        name="L3_investigate_cli_parsing_edge_case",
        task="Investigate why CLI argument parser crashes when receiving negative number inputs",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "unknown", "crosses_module_boundary": "no", "crosses_service_boundary": "no", "fix_or_result_known": "no", "intermittent_or_concurrency": "no", "needs_new_structure": "no", "changes_security_or_payment_logic": "no", "reviews_security_sensitive_code": "no", "security_domain": "none", "changes_public_api_contract": "no", "changes_persisted_data": "no", "irreversible_or_ledger_or_crypto": "no", "changes_trust_boundary": "no", "blast_radius": "narrow", "silent_failure_material_harm": "no", "requires_code_understanding": "yes"},
        expected_level="L3",
        expected_unresolved=("files_touched",),
    ),
    BenchmarkCase(
        name="L3_debug_unexpected_null_pointer",
        task="Track down unexpected NullPointerException when parsing malformed incoming webhook payload",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "unknown", "crosses_module_boundary": "no", "crosses_service_boundary": "no", "fix_or_result_known": "no", "intermittent_or_concurrency": "no", "needs_new_structure": "no", "changes_security_or_payment_logic": "no", "reviews_security_sensitive_code": "no", "security_domain": "none", "changes_public_api_contract": "no", "changes_persisted_data": "no", "irreversible_or_ledger_or_crypto": "no", "changes_trust_boundary": "no", "blast_radius": "narrow", "silent_failure_material_harm": "no", "requires_code_understanding": "yes"},
        expected_level="L3",
        expected_unresolved=("files_touched",),
    ),
    BenchmarkCase(
        name="L3_investigate_cache_miss_spike",
        task="Analyze sudden unexplained spike in cache misses for user profile session data",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "unknown", "crosses_module_boundary": "no", "crosses_service_boundary": "no", "fix_or_result_known": "no", "intermittent_or_concurrency": "no", "needs_new_structure": "no", "changes_security_or_payment_logic": "no", "reviews_security_sensitive_code": "no", "security_domain": "none", "changes_public_api_contract": "no", "changes_persisted_data": "no", "irreversible_or_ledger_or_crypto": "no", "changes_trust_boundary": "no", "blast_radius": "narrow", "silent_failure_material_harm": "no", "requires_code_understanding": "yes"},
        expected_level="L3",
        expected_unresolved=("files_touched",),
    ),
    BenchmarkCase(
        name="L3_debug_serialization_field_mismatch",
        task="Locate field mismatch causing datetime serialization error in payload generator",
        task_type="implementation",
        facts={"mechanical_only": "no", "files_touched": "unknown", "crosses_module_boundary": "no", "crosses_service_boundary": "no", "fix_or_result_known": "no", "intermittent_or_concurrency": "no", "needs_new_structure": "no", "changes_security_or_payment_logic": "no", "reviews_security_sensitive_code": "no", "security_domain": "none", "changes_public_api_contract": "no", "changes_persisted_data": "no", "irreversible_or_ledger_or_crypto": "no", "changes_trust_boundary": "no", "blast_radius": "narrow", "silent_failure_material_harm": "no", "requires_code_understanding": "yes"},
        expected_level="L3",
        expected_unresolved=("files_touched",),
    ),
]

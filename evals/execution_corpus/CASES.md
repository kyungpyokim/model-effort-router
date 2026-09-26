# Execution Corpus v1 — frozen manifest

- Freeze revision: `v1`
- Freeze date: 2026-09-26
- Frozen before any live model run: this record and `cases.json` were committed before any Codex, Claude, or classifier invocation for the E2E token/cost benchmark.
- Selection rule: 15 cases drawn from the existing routing-corpus candidate metadata (`scripts/benchmark_corpus.py`), three per level L1-L5, task types restricted to `implementation`, `local_refactoring`, and `architectural_refactoring`, with at least one L5 case on the elevated/security tier.
- After freeze: cases are never removed or replaced because of model failures or inconvenient results, and gold metadata is never edited based on model behavior. Fixture or test bugs require an explicit corpus revision note and a complete rerun of affected comparisons.

## Frozen cases (manifest order)

| # | Case ID | Level | Tier | Task type |
|---|---------|-------|------|-----------|
| 1 | L1_doc_typo_fix | L1 | standard | implementation |
| 2 | L1_unused_import_cleanup | L1 | standard | local_refactoring |
| 3 | L1_rename_local_variable | L1 | standard | local_refactoring |
| 4 | L2_simple_bug_fix | L2 | standard | implementation |
| 5 | L2_single_file_helper | L2 | standard | implementation |
| 6 | L2_local_extract_function | L2 | standard | local_refactoring |
| 7 | L3_add_feature_controller_service | L3 | standard | implementation |
| 8 | L3_local_refactor_three_files | L3 | standard | local_refactoring |
| 9 | L3_refactor_logger_four_files | L3 | standard | local_refactoring |
| 10 | L4_public_api_change | L4 | standard | implementation |
| 11 | L4_cross_module_refactor | L4 | standard | architectural_refactoring |
| 12 | L4_rename_type_across_ten_files | L4 | standard | local_refactoring |
| 13 | L5_concurrency_race_condition | L5 | standard | implementation |
| 14 | L5E_security_oauth_token_refresh | L5 | elevated | implementation |
| 15 | L5_new_plugin_architecture | L5 | standard | implementation |

Machine-readable source of truth: `evals/execution_corpus/cases.json` (this table must list the same IDs in the same order).

## Fixture freeze (completed 2026-09-26)

- Manifest revision: `v1`. All 15 fixture snapshots under `evals/execution_corpus/fixtures/` were completed and frozen in commit `test: complete frozen e2e execution fixtures` (2026-09-26) — the fixture-freeze boundary for this corpus, landing with this record.
- From this boundary, all later live smoke and benchmark results must use these exact fixture snapshots (fresh copies of the committed directories) unless a documented corpus revision triggers paired reruns.

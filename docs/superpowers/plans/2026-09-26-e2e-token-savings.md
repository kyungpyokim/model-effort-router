# E2E Token & Cost Savings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible Phase 1 Codex-only evaluation that measures C (Fixed-Ceiling), Routed, and B (Executor-Ceiling) end-to-end token usage, API-equivalent estimated cost, quality, retry/fix behavior, and wall time on a frozen 15-case execution corpus.

**Architecture:** Instrument the real production pipeline only after route argv validation, with provider-specific structured-output parsing isolated behind a provider-neutral usage interface. Keep execution-corpus loading, pricing, baseline-mode resolution, orchestration, and reporting in focused eval modules so production routing semantics remain unchanged; the harness runs every case from a fresh fixture snapshot and records complete raw/normalized artifacts. C and Routed share production stage policy but differ in metadata/profile selection; B is a simpler fixed executor-ceiling system baseline.

**Tech Stack:** Python 3, existing Model-Effort-Router scripts, Codex CLI structured JSON output, stdlib `dataclasses`/`json`/`pathlib`/`subprocess`, pytest/unittest as already used by the repository, deterministic local fixture tests.

**Spec:** `docs/superpowers/specs/2026-09-26-e2e-token-savings-design.md` (approved at commit `60c19cd`; implementation must use that committed version, not an older attachment/export).

**Source-lock note:** The local repository tunnel was unavailable while this plan was authored, so existing concrete production return-type names and current line numbers were not guessed. Tasks 6 and 8 begin with mandatory source-map gates; implementation must bind the named eval helpers to the repository's actual existing route/profile/stage types before writing those tests, and must not invent a parallel production routing schema.

## Global Constraints

- Phase 1 provider is Codex/OpenAI only; Claude support is interface preparation only, not a Phase 1 implementation target.
- Do not change route schema/version for telemetry; keep the current route artifact version unchanged.
- Telemetry flags are injected only after `validate_argv()` succeeds and must be removable back to the exact validated argv.
- Instrumentation off must preserve the legacy command/output/exit/stderr path under deterministic mocks.
- `MODEL_EFFORT_ROUTER_INSTRUMENT_USAGE=1` enables instrumentation; `MODEL_EFFORT_ROUTER_USAGE_JSONL=<path>` selects the sink. Neither environment value may become model CLI argv.
- C uses frozen gold metadata, no classifier, production stage policy, and the highest allowed role/stratum profile for every activated model stage.
- B uses the gold `task_type` only to select the executor matrix family, then always chooses that family's highest implementer profile; gold level/tier never lower or raise B's executor profile.
- Routed uses the real classifier/routing/fallback path. Classification errors and fallback usage are measured, not corrected with gold metadata.
- Execution Corpus v1 is exactly 15 cases: L1-L5 three each; allowed task types are `implementation`, `local_refactoring`, and `architectural_refactoring`; at least one L5 case is elevated/security.
- Freeze `evals/execution_corpus/CASES.md` and the machine-readable manifest before inspecting any live Codex result. After freeze, failed/inconvenient cases are not removed or replaced.
- Every C/B/Routed run starts from a fresh copy of the exact same fixture snapshot for that case; fixtures have no external network dependency and use deterministic acceptance tests.
- C/Routed pairs are adjacent. Freeze schedule seed `20260926`: shuffle frozen case IDs with `random.Random(20260926)`, then alternate first mode by schedule position starting with C, yielding exactly 8 C-first and 7 Routed-first pairs. Record actual start order and observed cached-input share; do not reorder after seeing results.
- Phase 1 benchmark count is 45 pipeline runs: 15 C + 15 Routed + 15 B, excluding smoke/validation runs.
- Primary aggregate saving uses pooled/micro totals; equal-level macro is secondary. Never average case-level saving percentages naively.
- `estimated_cost_usd` is an API-equivalent estimate from a committed official-source pricing snapshot, never an assertion about subscription billing.
- Cached input, cache write, output, and reasoning fields follow provider billing semantics; never double-count cached input or reasoning tokens in token or cost totals.
- Execution failure with complete telemetry remains a valid cost/token observation. Partial/missing required usage marks the run `telemetry_invalid`; it is never silently zeroed or dropped.
- A `quality-preserving` description is permitted only when no case regresses from C acceptance-pass to Routed acceptance-fail and the elevated/security case introduces no new Routed failure; otherwise report token/cost saving without that descriptor.
- Structural stage-skip savings are not attributed to C-vs-Routed. Numeric structural saving requires a separate no-skip ablation, outside Phase 1 unless explicitly added later.
- Use the repository's existing test runner conventions. Commands below use `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest`; if the repository already wraps this command, use that wrapper without changing test semantics.

## File Structure

- Modify `scripts/pipeline.py` — add the post-validation instrumentation seam and preserve logical stage output.
- Conditionally modify `scripts/classifier.py` — only if source inspection proves classifier model calls bypass the pipeline execution seam; reuse the same instrumentation helper rather than creating classifier-specific accounting.
- Reuse `scripts/commands.py` and its current `validate_argv()`/command generation contract; do not expand route grammar for telemetry.
- Create `scripts/e2e_usage.py` — provider-neutral usage types, Codex argv instrumentation/strip, JSONL parsing, logical-output extraction, usage recorder.
- Create `scripts/e2e_pricing.py` — static pricing snapshot loading and provider-specific API-equivalent cost calculation.
- Create `scripts/e2e_corpus.py` — execution-case manifest loading/validation and fresh fixture-copy helpers.
- Create `scripts/e2e_modes.py` — C/B/Routed eval-mode resolution around existing production policy/profile APIs; no parallel routing schema.
- Create `scripts/e2e_reporting.py` — pair validity, pooled/macro aggregation, quality gate, and Markdown/JSON report generation.
- Create `scripts/eval_e2e_pipeline.py` — thin CLI/orchestrator for dry-run/live execution, pair scheduling, artifact directories, and report invocation.
- Create `config/model-pricing.json` — committed official-source price snapshot.
- Create `evals/execution_corpus/cases.json` — machine-readable frozen 15-case manifest.
- Create `evals/execution_corpus/CASES.md` — human-readable frozen corpus record and freeze metadata.
- Create `evals/execution_corpus/fixtures/<case-id>/...` — 15 self-contained fixture repositories and deterministic tests.
- Create/modify focused tests under `tests/` as named below.

## Review Focus

1. **Classifier usage can bypass `pipeline.py`:** every real classifier/fallback model invocation must still emit normalized usage into the Routed run sink. Task 6 adds a subprocess-seam coverage test that fails if classifier usage is absent.
2. **Structured output can be malformed or usage can be missing on a non-zero exit:** preserve logical output/raw trace where possible, classify usage as `partial|missing`, and mark the run telemetry-invalid rather than zero-cost. Task 5 owns these parser/error tests.
3. **Cached input/reasoning subfields can be double-counted:** token totals and API-equivalent cost must follow provider semantics, including cached-input subtraction and reasoning-in-output behavior. Task 7 owns explicit anti-double-counting tests.
4. **Run order/provider cache can bias C-vs-Routed:** adjacent pair execution must honor the frozen 8/7 counterbalance and record cached-input share/order without post-result reordering. Task 8 owns deterministic schedule tests.
5. **Fixture mutation can leak between modes/retries:** each run must receive a fresh snapshot and cannot mutate the frozen source fixture. Task 8 owns contamination/isolation tests.

---

### Task 1: Freeze Execution Corpus Manifest Before Any Live Model Call

**Files:**
- Create: `evals/execution_corpus/cases.json`
- Create: `evals/execution_corpus/CASES.md`
- Create: `scripts/e2e_corpus.py`
- Test: `tests/test_e2e_corpus.py`

**Interfaces:**
- Consumes: existing Routing Corpus case definitions (`scripts/benchmark_corpus.py` / `scripts/benchmark_cases/...`) only as candidate metadata; no live model output.
- Produces: `ExecutionCase` and `load_execution_cases(path: Path) -> tuple[ExecutionCase, ...]`; `validate_execution_corpus(cases: Sequence[ExecutionCase], repo_root: Path) -> None`; frozen `cases.json` with 15 case IDs and gold metadata.

- [ ] **Step 1: Inspect the existing corpus types and enumerate eligible candidates without invoking any model**

Run:

```bash
rg -n "class BenchmarkCase|GOLDEN_BENCHMARK_CASES|task_type|expected_level|expected_tier" scripts tests
```

Expected: locate the existing case model and the 100-case corpus definitions. Do not run `codex`, `claude`, Jev, or any live classifier in this step.

- [ ] **Step 2: Write failing corpus-contract tests**

In `tests/test_e2e_corpus.py`, assert that `load_execution_cases()` returns exactly 15 unique cases, `Counter(level) == {L1:3, L2:3, L3:3, L4:3, L5:3}`, every task type is in the approved three-value set, at least one L5 case is elevated/security, every `fixture_dir` is relative and stays under `evals/execution_corpus/fixtures`, every `test_cmd` is non-empty, and every case has a non-empty acceptance description.

Also assert `CASES.md` lists the same 15 IDs in the same frozen order as `cases.json` and records freeze revision `v1` plus the freeze date before any live run.

- [ ] **Step 3: Run the corpus tests to verify they fail**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_e2e_corpus.py -v
```

Expected: FAIL because the loader/manifest do not exist yet.

- [ ] **Step 4: Implement `ExecutionCase` and manifest validation in `scripts/e2e_corpus.py`**

Use a frozen dataclass with these fields: `name: str`, `task_type: str`, `level: str`, `tier: str`, `task: str`, `fixture_dir: Path`, `test_cmd: str`, `acceptance: str`. Use stdlib JSON; do not add a YAML dependency solely for this eval.

- [ ] **Step 5: Select and record the 15 cases before inspecting any live model result**

Populate `cases.json` and `CASES.md` from existing eligible corpus tasks, satisfying the approved distribution and elevated/security requirement. Selection is frozen by this commit: later fixture/test bugs require a corpus revision note and rerun; model failure/cost is never grounds for replacement.

- [ ] **Step 6: Run the corpus tests**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_e2e_corpus.py -v
```

Expected: PASS for manifest-only checks; fixture-existence/acceptance checks may remain explicitly skipped until Tasks 2-4 and must not be silently ignored.

- [ ] **Step 7: Commit the frozen manifest before any live Codex smoke**

```bash
git add evals/execution_corpus/cases.json evals/execution_corpus/CASES.md scripts/e2e_corpus.py tests/test_e2e_corpus.py
git commit -m "test: freeze e2e execution corpus manifest"
```

---

### Task 2: Build and Validate L1-L2 Execution Fixtures

**Files:**
- Create: `evals/execution_corpus/fixtures/<six L1-L2 case ids>/...`
- Modify: `tests/test_e2e_corpus.py`
- Create: `tests/test_execution_fixtures.py`

**Interfaces:**
- Consumes: the six frozen L1/L2 entries from `cases.json` and `ExecutionCase.test_cmd`.
- Produces: six self-contained repositories whose initial state exhibits the target defect/change and whose deterministic tests pass only after the task is correctly implemented.

- [ ] **Step 1: Add failing meta-tests for all six L1/L2 fixtures**

`tests/test_execution_fixtures.py` should parameterize over the frozen cases and assert: fixture directory exists; no symlink escapes the fixture root; no test requires network; the configured test command can be launched locally; repeated initial-state test runs return the same exit status/output classification.

- [ ] **Step 2: Run the meta-tests to verify failure**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_execution_fixtures.py -k 'L1 or L2' -v
```

Expected: FAIL because fixture directories are absent.

- [ ] **Step 3: Create the six minimal L1/L2 fixture repositories**

Keep each fixture bounded to the smallest code/docs surface that preserves the frozen task semantics. Include only local deterministic dependencies; prefer stdlib or checked-in tiny project metadata over network installation.

- [ ] **Step 4: Verify each fixture's precondition and determinism**

For each case, execute its frozen `test_cmd` twice from a fresh copy. The initial fixture must produce the expected failing/precondition state consistently; record that expected initial outcome in the fixture's local README or manifest metadata if needed by the meta-test.

- [ ] **Step 5: Run the L1/L2 fixture meta-tests**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_execution_fixtures.py -k 'L1 or L2' -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add evals/execution_corpus/fixtures tests/test_execution_fixtures.py tests/test_e2e_corpus.py
git commit -m "test: add L1 L2 e2e execution fixtures"
```

---

### Task 3: Build and Validate L3 Execution Fixtures

**Files:**
- Create: `evals/execution_corpus/fixtures/<three L3 case ids>/...`
- Modify: `tests/test_execution_fixtures.py`

**Interfaces:**
- Consumes: the three frozen L3 entries from `cases.json`.
- Produces: three deterministic L3 fixture repositories with meaningful local acceptance tests.

- [ ] **Step 1: Extend the fixture meta-test to cover the three L3 cases**

Assert the same isolation/determinism properties as Task 2 and verify that the acceptance test actually distinguishes the initial state from a known-correct local patch prepared only for fixture validation.

- [ ] **Step 2: Run to verify failure**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_execution_fixtures.py -k L3 -v
```

Expected: FAIL until the three fixtures exist.

- [ ] **Step 3: Create the three L3 fixtures and deterministic acceptance tests**

Keep multi-file scope only where the frozen task needs it. Do not add unrelated complexity merely to make the level look harder.

- [ ] **Step 4: Run fixture tests twice from fresh copies**

Expected: identical initial-state outcomes across repeated copies.

- [ ] **Step 5: Run meta-tests and commit**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_execution_fixtures.py -k L3 -v
git add evals/execution_corpus/fixtures tests/test_execution_fixtures.py
git commit -m "test: add L3 e2e execution fixtures"
```

---

### Task 4: Build L4-L5 Fixtures Including Elevated Security and Close the Corpus Freeze

**Files:**
- Create: `evals/execution_corpus/fixtures/<six L4-L5 case ids>/...`
- Modify: `tests/test_execution_fixtures.py`
- Modify: `tests/test_e2e_corpus.py`
- Modify: `evals/execution_corpus/CASES.md`

**Interfaces:**
- Consumes: the six frozen L4/L5 entries, including at least one L5 elevated/security case.
- Produces: all 15 executable fixtures; a corpus validation suite with no fixture-related skips.

- [ ] **Step 1: Add L4/L5 and elevated-security fixture tests**

For the security case, assert external network is unnecessary and the fixture locally models the security-sensitive behavior (for example token refresh/state rotation/concurrency) with deterministic tests. Do not require a live OAuth provider.

- [ ] **Step 2: Run to verify failure**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_execution_fixtures.py -k 'L4 or L5' -v
```

Expected: FAIL until the six fixtures exist.

- [ ] **Step 3: Create the six L4/L5 fixtures**

Use bounded repositories with enough files/state transitions to preserve the frozen task intent. The elevated/security fixture must exercise the relevant policy risk path by metadata but must remain locally testable.

- [ ] **Step 4: Remove all temporary fixture skips and validate the entire frozen corpus**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_e2e_corpus.py tests/test_execution_fixtures.py -v
```

Expected: 15/15 fixture discovery and deterministic-precondition checks PASS with no fixture-related skip.

- [ ] **Step 5: Record the completed fixture freeze in `CASES.md`**

Record the manifest revision/commit boundary and state explicitly that all later live smoke/benchmark results must use these fixture snapshots unless a documented corpus revision triggers paired reruns.

- [ ] **Step 6: Commit before any Codex structured-output smoke**

```bash
git add evals/execution_corpus tests/test_e2e_corpus.py tests/test_execution_fixtures.py
git commit -m "test: complete frozen e2e execution fixtures"
```

---

### Task 5: Add Provider-Neutral Usage Records and Codex Structured-Output Parsing

**Files:**
- Create: `scripts/e2e_usage.py`
- Create: `tests/test_e2e_usage.py`
- Create: `tests/fixtures/e2e_usage/codex_complete.jsonl`
- Create: `tests/fixtures/e2e_usage/codex_partial.jsonl`
- Create: `tests/fixtures/e2e_usage/codex_malformed.jsonl`

**Interfaces:**
- Consumes: validated provider argv, captured process stdout/stderr, stage metadata, process exit code, and wall time.
- Produces:
  - `UsageContext(run_id: str, case_id: str, mode: str, stage: str, attempt: int, model: str, effort: str | None)`
  - `NormalizedUsage(input_tokens: int, cached_input_tokens: int, cache_write_tokens: int, output_tokens: int, reasoning_tokens: int, total_tokens: int, usage_status: Literal["complete","partial","missing"])`
  - `ParsedProviderOutput(logical_output: str, usage: NormalizedUsage, raw_events: tuple[dict, ...])`
  - `instrument_execution_argv(provider: str, validated_argv: Sequence[str]) -> list[str]`
  - `strip_instrumentation(provider: str, execution_argv: Sequence[str]) -> list[str]`
  - `parse_codex_jsonl(stdout: str, context: UsageContext, *, exit_code: int, wall_time_ms: int) -> ParsedProviderOutput`
  - `append_usage_jsonl(path: Path, context: UsageContext, parsed: ParsedProviderOutput) -> None`

- [ ] **Step 1: Write argv invariant tests before implementation**

Use representative validated Codex argv produced by the existing `commands.py` contract. Assert instrumentation adds only the provider-owned structured-output flag at the valid Codex CLI position, and `strip_instrumentation(instrument_execution_argv(validated)) == validated` byte-for-byte/list-element-for-list-element.

- [ ] **Step 2: Write parser tests using checked-in synthetic JSONL fixtures**

Tests must cover: complete usage; cached input as a subset of input; reasoning as a subset of output where reported; final logical assistant output extraction; malformed unrelated event tolerance; partial usage; missing usage; non-zero exit with recoverable usage. Assert `total_tokens` never adds cached/reasoning subsets twice.

- [ ] **Step 3: Run to verify failure**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_e2e_usage.py -v
```

Expected: FAIL because `scripts/e2e_usage.py` does not exist.

- [ ] **Step 4: Implement the usage dataclasses, Codex argv adapter, parser, and JSONL recorder**

Keep provider-specific event-shape logic inside the Codex parser. The recorder writes one normalized invocation record per model call and does not infer zero usage from absence.

- [ ] **Step 5: Run tests**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_e2e_usage.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/e2e_usage.py tests/test_e2e_usage.py tests/fixtures/e2e_usage
git commit -m "feat: add Codex usage telemetry primitives"
```

---

### Task 6: Wire Usage Instrumentation Into the Real Pipeline and Classifier Path

**Files:**
- Modify: `scripts/pipeline.py`
- Conditionally modify: `scripts/classifier.py`
- Reuse: `scripts/commands.py`
- Test: `tests/test_pipeline_usage_instrumentation.py`
- Test: `tests/test_classifier_usage_instrumentation.py`

**Interfaces:**
- Consumes: Task 5 `instrument_execution_argv()`, `parse_codex_jsonl()`, `append_usage_jsonl()`.
- Produces: instrumented execution only when `MODEL_EFFORT_ROUTER_INSTRUMENT_USAGE=1`; unchanged legacy execution otherwise; complete Routed classifier/fallback usage coverage.

- [ ] **Step 1: Map the current model subprocess seams before editing**

Run:

```bash
rg -n "def run_capture|run_capture\(|validate_argv\(|subprocess\.(run|Popen)|codex exec|claude -p|classif" scripts tests
```

Expected: identify the exact `pipeline.py` post-validation execution point and every classifier/fallback model CLI call. If classifier already flows through the same helper, do not modify `classifier.py`; if it bypasses that helper, wire only the shared Task 5 instrumentation helper into that existing classifier subprocess seam.

- [ ] **Step 2: Write instrumentation-off regression tests**

With deterministic mocked subprocess bytes, assert env-disabled execution sends the exact legacy argv, returns byte-identical logical stdout, propagates the same exit code, and preserves stderr handling. Do not use live model text as the oracle.

- [ ] **Step 3: Write instrumentation-on pipeline tests**

Set the two approved telemetry env vars, feed mocked Codex JSONL through `run_capture`, and assert: the actual execution argv is the validated argv plus only the trusted structured-output flag; downstream stages receive only reconstructed logical assistant output; `usage.jsonl` gets one record with the correct stage/attempt/model/effort; raw JSONL never leaks into the next model prompt.

- [ ] **Step 4: Write classifier-path coverage tests**

Exercise the real Routed classification entry path under mocks and assert a classifier model invocation creates a `stage="classifier"` usage record. Exercise the existing fallback path and assert fallback invocations are also recorded. This test is mandatory even if no `classifier.py` edit is needed.

- [ ] **Step 5: Run tests to verify failure**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_pipeline_usage_instrumentation.py tests/test_classifier_usage_instrumentation.py -v
```

Expected: FAIL before wiring.

- [ ] **Step 6: Implement the smallest post-validation instrumentation hook**

Do not widen `validate_argv()` or route grammar. Read enable/sink environment values only for telemetry behavior. Stage/run metadata must be passed to the recorder through existing call context or harness-owned metadata; never splice metadata/env content into model argv.

- [ ] **Step 7: Run focused and existing argv validation tests**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_pipeline_usage_instrumentation.py tests/test_classifier_usage_instrumentation.py -v
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -k 'argv or command or pipeline or classifier' -v
```

Expected: PASS, with route argv validation behavior unchanged.

- [ ] **Step 8: Commit**

```bash
git add scripts/pipeline.py scripts/classifier.py tests/test_pipeline_usage_instrumentation.py tests/test_classifier_usage_instrumentation.py
git commit -m "feat: instrument real pipeline usage accounting"
```

If `scripts/classifier.py` was not modified, omit it from `git add`.

---

### Task 7: Add Versioned Pricing Snapshot and OpenAI Billing Adapter

**Files:**
- Create: `config/model-pricing.json`
- Create: `scripts/e2e_pricing.py`
- Create: `tests/test_e2e_pricing.py`

**Interfaces:**
- Consumes: `NormalizedUsage` from Task 5 and a committed pricing snapshot.
- Produces:
  - `PricingSnapshot(snapshot_date: str, currency: str, sources: Mapping[str, str], providers: Mapping[str, ...])`
  - `load_pricing(path: Path) -> PricingSnapshot`
  - `estimate_api_equivalent_cost_usd(provider: str, model: str, usage: NormalizedUsage, pricing: PricingSnapshot) -> Decimal`

- [ ] **Step 1: Write failing pricing tests**

Cover: uncached input; cached input with `uncached_input = input_tokens - cached_input_tokens`; cache-write rate when present; output; reasoning included in output (must not be charged twice); future separate-reasoning branch; unknown model/rate fails explicitly; negative derived uncached input is rejected as invalid usage.

- [ ] **Step 2: Run to verify failure**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_e2e_pricing.py -v
```

Expected: FAIL because adapter/snapshot do not exist.

- [ ] **Step 3: Implement the pricing loader and OpenAI adapter**

Use `Decimal` for currency math. Keep the raw usage untouched; compute billing quantities in the adapter. The snapshot schema contains `snapshot_date`, `currency`, official source metadata, per-model input/cached-input/cache-write/output rates, and `reasoning_billing`.

- [ ] **Step 4: Populate `config/model-pricing.json` from the official provider pricing source immediately before benchmark execution**

Do not add live lookup code. If exact rates are not yet ready during implementation, tests use a dedicated fixture snapshot; the committed production snapshot must contain no placeholder/null rate for any Phase 1 model before Task 10's live smoke/full readiness gate.

- [ ] **Step 5: Run tests and commit**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_e2e_pricing.py -v
git add config/model-pricing.json scripts/e2e_pricing.py tests/test_e2e_pricing.py
git commit -m "feat: add versioned e2e pricing adapter"
```

---

### Task 8: Implement C/B/Routed Mode Resolution, Fresh Snapshots, and Counterbalanced Harness Scheduling

**Files:**
- Create: `scripts/e2e_modes.py`
- Create: `scripts/eval_e2e_pipeline.py`
- Modify: `scripts/e2e_corpus.py`
- Create: `tests/test_e2e_modes.py`
- Create: `tests/test_eval_e2e_pipeline.py`

**Interfaces:**
- Consumes: existing production stage-policy/profile APIs, frozen `ExecutionCase`, Task 5 telemetry, Task 7 pricing.
- Produces:
  - `EvalMode = Literal["c","routed","b"]`
  - `resolve_c_plan(...)` — bind its parameters/return annotation in Step 1 to the repository's exact existing production stage-policy/route type; it must not introduce a new route schema.
  - `resolve_b_executor_profile(...)` — bind its return annotation in Step 1 to the exact existing production implementer-profile type; task type selects the matrix family and level/tier do not alter the selected family ceiling.
  - `fresh_fixture_copy(case: ExecutionCase, run_root: Path) -> Path`
  - `build_pair_schedule(cases: Sequence[ExecutionCase], seed: int = 20260926) -> tuple[PairScheduleEntry, ...]`
  - CLI: `scripts/eval_e2e_pipeline.py --mode c|routed|b [--case ID] [--live] [--seed N]`
  - Run artifact root: `runs/e2e-token-savings/<run-id>/<case-id>/<mode>/` containing `usage.jsonl`, `summary.json`, `test.log`, `stdout.log`, `stderr.log`, and optional `raw/` structured-event traces.

- [ ] **Step 1: Inspect and lock the existing policy/profile interfaces instead of creating a parallel router**

Run:

```bash
rg -n "highest_allowed_profile|stage.policy|stage_policy|trivial_edit|risk_tier|planner|reviewer|implementer" scripts tests
```

Use the existing route/profile dataclasses and stage-policy function. The only new abstraction in `e2e_modes.py` is eval-mode selection around those production APIs.

- [ ] **Step 2: Write C-mode tests**

For representative L1-L5 frozen metadata, assert no classifier is invoked; production stage policy is evaluated from gold metadata; every activated model stage gets `highest_allowed_profile(...)`; skipped stages match production policy. Include an L1 trivial-edit case to prove stage skip is shared structural policy rather than a Routed-only optimization.

- [ ] **Step 3: Write B-mode tests**

Assert gold `task_type` selects the executor matrix family only, then B picks the highest implementer profile available in that family across levels. Vary gold level and tier while holding task type constant and assert the B executor profile does not change. Assert planner/reviewer/classifier are absent and retry uses the same fixed executor ceiling.

- [ ] **Step 4: Write Routed-mode tests**

Assert the harness invokes the real runtime classifier, uses the classified metadata to drive the production stage policy/profile selection, and never replaces a mismatch with gold metadata. Assert classifier fallback remains on the measured route.

- [ ] **Step 5: Write fresh-copy and contamination tests**

Run C against a copied fixture, mutate files, then create a Routed copy for the same case. Assert the Routed copy equals the frozen source snapshot rather than C's mutated worktree. Repeat for retry attempts according to production retry semantics.

- [ ] **Step 6: Write deterministic pair-schedule tests**

For the frozen 15 IDs, assert seed `20260926` shuffles IDs deterministically, first mode alternates by scheduled position beginning with C, each C/Routed pair is adjacent, exactly 8 are C-first and 7 Routed-first, and the schedule is recorded rather than recomputed after results. Record both scheduled and actual start order; an execution-order deviation gets an explicit reason field and never triggers post-result reordering. B is scheduled only after all 30 C/Routed runs.

- [ ] **Step 7: Write dry-run tests**

`--live` absent must make zero model calls. Dry-run validates all fixture paths/test commands/pricing/model-profile availability; resolves C/B stage policies; validates Routed classifier/routing configuration and graph-construction paths without claiming the actual live Routed stage graph. Also assert the harness pre-creates the exact run artifact layout without mutating frozen fixtures.

- [ ] **Step 8: Run tests to verify failure, then implement minimal mode/harness code**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_e2e_modes.py tests/test_eval_e2e_pipeline.py -v
```

Expected before implementation: FAIL. After implementation: PASS.

- [ ] **Step 9: Verify the complete dry-run across 15 cases**

```bash
python3 scripts/eval_e2e_pipeline.py --mode c
python3 scripts/eval_e2e_pipeline.py --mode routed
python3 scripts/eval_e2e_pipeline.py --mode b
```

Expected: zero live model calls; 15 cases discovered; pair schedule and artifact layout validated; no placeholder pricing/model profile; no fixture path/test command error.

- [ ] **Step 10: Commit**

```bash
git add scripts/e2e_modes.py scripts/e2e_corpus.py scripts/eval_e2e_pipeline.py tests/test_e2e_modes.py tests/test_eval_e2e_pipeline.py
git commit -m "feat: add e2e baseline and routed harness modes"
```

---

### Task 9: Add Run Validity, Aggregation, Quality Gate, and Markdown/JSON Reporting

**Files:**
- Create: `scripts/e2e_reporting.py`
- Modify: `scripts/eval_e2e_pipeline.py`
- Create: `tests/test_e2e_reporting.py`

**Interfaces:**
- Consumes: per-run summary JSON, usage JSONL, pricing snapshot, frozen case metadata, actual pair order.
- Produces:
  - `RunSummary` / `PairSummary` provider-neutral records.
  - `is_primary_metric_valid_pair(c: RunSummary, routed: RunSummary) -> bool`
  - `pooled_saving(baseline_values: Sequence[Decimal|int], routed_values: Sequence[Decimal|int]) -> Decimal`
  - `aggregate_by_level(...)`
  - `quality_preserving_allowed(c_pairs: Sequence[PairSummary]) -> bool`
  - `render_markdown_report(...) -> str`
  - report path `docs/<date>-e2e-token-savings.md` plus machine-readable aggregate JSON in the run directory.

- [ ] **Step 1: Write validity tests**

Assert execution failure with complete telemetry remains included in token/cost totals and quality failure counts. Assert partial/missing required telemetry makes the C/Routed pair invalid for primary token/cost KPI, preserves the case in the report, and increments `telemetry_invalid`; never substitute zero. Add timeout/provider-failure cases: complete pre-failure usage stays billable/valid as an execution failure, while partial usage stays diagnostic/lower-bound only. Distinguish harness-level infrastructure retry count from pipeline retry/fix count.

- [ ] **Step 2: Write pooled/macro aggregation tests**

Use a small synthetic set where naive mean(case saving %) differs from `1 - sum(Routed)/sum(C)`. Assert pooled/micro is primary, per-level pooled values are correct, equal-level macro is the arithmetic mean of L1-L5 pooled savings, and coverage prints `valid_pairs/15`.

- [ ] **Step 3: Write quality-preserving wording tests**

Assert the descriptor is allowed only when (a) no C-pass case becomes Routed-fail on deterministic acceptance and (b) the elevated/security case has no new Routed failure. Assert any violation removes the descriptor while leaving numeric token/cost savings visible.

- [ ] **Step 4: Write report composition tests**

Report must include B/C/Routed token and estimated-cost columns, level breakdown, per-stage composition, retry/fix tokens, success/test/review outcomes, classification mismatches, stage-skip counts, valid-pair coverage, pricing snapshot date/source, provider/CLI version, actual pair start order, observed cached-input share, limitations, and the label `Estimated API-equivalent cost`.

Assert A is absent unless a same-fixture A mode was explicitly run.

- [ ] **Step 5: Run to verify failure, then implement reporting**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_e2e_reporting.py -v
```

Expected before implementation: FAIL. After implementation: PASS.

- [ ] **Step 6: Integrate report generation into the harness without changing execution semantics**

The harness writes per-case raw artifacts first, then aggregates. A report-generation failure must not delete run artifacts or rerun model calls automatically.

- [ ] **Step 7: Run focused tests and commit**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_e2e_reporting.py tests/test_eval_e2e_pipeline.py -v
git add scripts/e2e_reporting.py scripts/eval_e2e_pipeline.py tests/test_e2e_reporting.py tests/test_eval_e2e_pipeline.py
git commit -m "feat: report e2e routing token and cost savings"
```

---

### Task 10: Freeze Real Codex Event Fixtures, Verify No Regression, and Gate the 45-Run Benchmark

**Files:**
- Modify: `tests/fixtures/e2e_usage/codex_complete.jsonl`
- Modify: `tests/fixtures/e2e_usage/codex_partial.jsonl` only if the installed CLI schema requires a more accurate representative fixture.
- Modify: `tests/test_e2e_usage.py`
- Modify: `evals/execution_corpus/CASES.md`
- Create after live benchmark only: `docs/2026-09-26-e2e-token-savings.md` (or the actual benchmark date if different)

**Interfaces:**
- Consumes: completed Tasks 1-9 and the installed Codex CLI.
- Produces: checked-in representative real structured-output fixtures, CLI-version metadata, full readiness verdict, and—only after explicit benchmark execution—the Phase 1 report.

- [ ] **Step 1: Verify the corpus freeze precedes all live smoke output**

Run:

```bash
git log --oneline -- evals/execution_corpus/CASES.md evals/execution_corpus/cases.json
```

Expected: the frozen corpus/fixture commits exist before the first live smoke artifact is captured.

- [ ] **Step 2: Run the two agreed live Codex structured-output smoke cases**

Capture raw stdout/stderr, `codex --version`, logical reconstructed output, and usage into an isolated ignored run directory. Use the actual post-validation instrumentation path; do not call a separate eval-only parser path.

Expected: both runs expose a parseable structured event stream and recoverable final logical output; any schema difference is visible before the 45-run benchmark.

- [ ] **Step 3: Replace synthetic complete-event fixtures with sanitized representative smoke fixtures and rerun parser tests**

Keep only the event fields necessary to pin schema/usage behavior; remove task/content secrets if any. Update parser code only if required by the observed CLI schema, then rerun:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_e2e_usage.py tests/test_pipeline_usage_instrumentation.py tests/test_classifier_usage_instrumentation.py -v
```

Expected: PASS using the real observed schema.

- [ ] **Step 4: Run one live E2E case in C and Routed mode as the final smoke**

Use a frozen case and fresh snapshots. Verify both runs produce complete stage usage, raw traces, logical pipeline behavior, deterministic test result, cost estimate, order metadata, and no fixture contamination. This smoke is not part of the 45 benchmark runs and must be labeled separately.

- [ ] **Step 5: Run the full non-live regression suite**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -v
ruff check scripts tests
```

Expected: PASS, excluding only repository-documented unrelated/environment-specific skips. Specifically confirm existing route argv validation tests still pass unchanged.

- [ ] **Step 6: Run bundle/build validation used by this repository**

If the repository still uses the known bundle commands, run:

```bash
python3 scripts/sync_bundle.py
python3 scripts/validate_bundle.py
```

Expected: PASS. If these scripts no longer exist, use the repository's current equivalent and record the command in the implementation log.

- [ ] **Step 7: Commit the validated instrumentation/parser state before benchmark**

```bash
git add scripts tests config evals/execution_corpus/CASES.md
git commit -m "test: validate e2e telemetry against Codex JSON events"
```

- [ ] **Step 8: Gate, but do not silently start, the 45-run benchmark**

Confirm all acceptance criteria: 15/15 fixtures, pricing rates present for every used model, C no-classifier, Routed real classifier/fallback usage, B fixed family ceiling, complete usage parsing, dry-run pass, 8/7 pair order frozen, and instrumentation-off regression pass.

The actual benchmark execution order is:

```text
30 adjacent C/Routed runs using the frozen pair schedule
then
15 B runs
```

Any harness-level provider retry must be separately labeled from pipeline retry/fix. Failed tasks remain observations. Telemetry-invalid attempts remain in audit history; if an instrumentation defect requires rerun, rerun the entire affected C/Routed pair from fresh snapshots.

- [ ] **Step 9: After the live benchmark, generate and verify the final report**

Expected report: `docs/<benchmark-date>-e2e-token-savings.md`, with pooled routing/system savings, level macro, valid-pair coverage, quality columns, pair order/cache share, pricing snapshot, CLI version, and limitations. Do not claim `quality-preserving` unless the predeclared quality gate returns true.

- [ ] **Step 10: Commit benchmark artifacts intended for version control**

```bash
git add docs/<benchmark-date>-e2e-token-savings.md config/model-pricing.json
git commit -m "docs: report e2e token and cost savings benchmark"
```

Keep bulky/raw run artifacts in the repository-approved ignored artifact root unless the project intentionally versions them.

---

## Final Verification Checklist

- [ ] `evals/execution_corpus/cases.json` and `CASES.md` contain the same frozen 15 IDs, 3 per L1-L5, with one L5 elevated/security case.
- [ ] All 15 fixtures are deterministic, network-free, and copied fresh per run.
- [ ] C does not invoke classifier and uses gold metadata + production stage policy + ceiling profiles.
- [ ] Routed invokes the real classifier/fallback path and all classifier usage is captured.
- [ ] B uses task type only to choose matrix family and always uses that family's highest implementer profile independent of gold level/tier.
- [ ] Route schema/validation are unchanged for telemetry; `strip_instrumentation(instrument_execution_argv(validated)) == validated`.
- [ ] Instrumentation-disabled pipeline behavior is unchanged under deterministic mocks.
- [ ] Structured provider output never leaks into downstream prompts.
- [ ] Complete/partial/missing usage semantics are explicit and missing usage is never zero-filled.
- [ ] Cached/reasoning token and cost fields cannot double-count.
- [ ] Dry-run invokes no model and does not claim a Routed live stage graph.
- [ ] Frozen pair schedule is adjacent and counterbalanced 8 C-first / 7 Routed-first.
- [ ] Primary reports use pooled micro ratios and show valid-pair coverage; level macro is secondary.
- [ ] Quality-preserving wording follows the predeclared acceptance/security rule.
- [ ] Phase 1 report labels cost as `Estimated API-equivalent cost` and excludes A from the E2E table unless A was explicitly run on the same fixtures.
- [ ] Full repository tests and existing bundle/validation checks pass before live benchmark execution.

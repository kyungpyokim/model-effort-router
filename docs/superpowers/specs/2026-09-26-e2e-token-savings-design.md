# E2E Token & Cost Savings Evaluation Design

- **Date:** 2026-09-26
- **Status:** Approved design / implementation pending
- **Primary provider (Phase 1):** Codex
- **Primary comparison:** C (Fixed-Ceiling Baseline) vs Routed
- **Secondary comparison:** B (Executor-Ceiling Baseline) vs Routed

## Purpose

The current routing evaluation primarily measures routing correctness and executor-only token behavior. That is insufficient to answer the product-level question:

> At equal or acceptable quality, does Model-Effort-Router reduce end-to-end token consumption and API-equivalent cost after classifier, planner, reviewer, retry, and fix-loop overhead are included?

This design adds E2E measurement to the **real pipeline** rather than an eval-only fork. It keeps the routing artifact/schema unchanged, instruments model CLI execution only after argv validation, separates the 100-case routing corpus from a smaller execution corpus with deterministic fixtures, and reports token, cost, quality, retry, and wall-time outcomes separately.

The design intentionally separates three kinds of effects:

1. **Routing effect:** dynamic model/effort selection vs a fixed role-appropriate ceiling profile under the same policy.
2. **System effect:** the complete routed pipeline vs a simpler executor-ceiling + deterministic-test/retry workflow.
3. **Structural effect:** savings caused by stage-skipping policy itself, such as trivial-edit plan/review omission. This is not attributed to model routing.

---

## Baseline terminology

### A — One-shot Executor Reference

A is the existing/simple reference: one executor call at the executor ceiling, with no retry loop. It is useful as an upper-bound/reference measurement for executor-only studies but is **not a Phase 1 E2E primary baseline**.

A must not be mixed into the B/C/Routed E2E table unless it is run against the same Execution Corpus fixtures and the same frozen task inputs. Existing Routing Corpus executor-only results remain a separate reference.

### B — Executor-Ceiling Baseline

B measures the value of the **whole routed system** relative to a simpler non-router workflow.

- No classifier.
- No planner.
- No reviewer.
- Gold `task_type` selects the executor **matrix family** only (for example, `implementation` vs `refactoring` family). Within that family, B always uses the highest implementer profile available across all levels (for example, Codex implementation/refactoring executor ceiling is the top implementer row, not a judge model). Gold level and gold tier do not alter this ceiling.
- Gold risk tier does not alter B's executor profile: under current router policy the `elevated`/`critical` tiers raise only planning/judging stages, and B has none. The gold tier is still recorded on B runs for reporting (so an elevated case is visibly covered) but it neither raises nor lowers the fixed executor ceiling.
- Deterministic test and retry/fix policy are the same as the routed experiment wherever applicable.
- Retry uses the same fixed executor-ceiling policy.
- Fixture snapshot, task text, payload policy, timeout, and test command are identical to the corresponding Routed run.

B answers:

> Is the complete routed pipeline more token/cost efficient than a strong fixed-executor workflow after planning/review/classification overhead is included?

### C — Fixed-Ceiling Baseline

C is the primary routing-specific baseline.

- Uses frozen gold metadata: `task_type`, `level`, and `tier`.
- Performs **no runtime classifier call**.
- Uses the same stage-policy function as Routed.
- For each model stage that the policy activates, selects the role/stratum `highest_allowed_profile(...)`.
- Does not dynamically downgrade model or effort.
- Uses the same deterministic test, retry/fix policy, payload limits, timeout, and fixture snapshot as Routed.

C answers:

> Given the correct task metadata and the same pipeline policy, how much do runtime classification plus dynamic model/effort choices save or cost?

### Routed

Routed is the production routing path being measured.

- Runtime classifier is executed and its token/cost overhead is included.
- The classified level/type/tier drives the normal stage policy and profile selection.
- Classifier fallback is part of the measured path and its usage is included.
- If classified metadata differs from frozen gold metadata, Routed still executes according to the classified result. The resulting stage/profile/retry difference is part of the real routing effect.

The policy implementation is the same between C and Routed, but the **actual stage graph may differ when classification is wrong**. Such differences are attributed to routing behavior, not to the standalone structural-saving estimate.

---

# 1. KPI definitions

## 1.1 Token accounting

For one run:

```text
T_run = sum(normalized_total_tokens for every model invocation in the run)
```

The sum includes, when present:

- classifier
- planner
- executor
- reviewer
- retry/fix executor calls
- re-review calls
- provider/model fallback calls

Deterministic local tests contribute zero model tokens.

Normalized usage must avoid double-counting provider subfields. For example, if a provider reports cached input as a subset of total input and reasoning as a subset of output, those fields are metadata for pricing/analysis and are **not added again** to `total_tokens`.

Provider adapters own the normalization semantics.

## 1.2 Primary routing KPIs

```text
Routing Token Saving
  = 1 - Routed_E2E_Tokens / C_E2E_Tokens

Routing Cost Saving
  = 1 - Routed_Estimated_Cost / C_Estimated_Cost
```

C is the **Fixed-Ceiling Baseline** defined above.

## 1.3 Secondary system KPIs

```text
System Token Saving
  = 1 - Routed_E2E_Tokens / B_E2E_Tokens

System Cost Saving
  = 1 - Routed_Estimated_Cost / B_Estimated_Cost
```

B is the **Executor-Ceiling Baseline** defined above.

## 1.4 Structural Saving

Structural savings such as L1 `trivial_edit` plan/review skipping must not be credited to model/effort routing.

Phase 1 keeps the same stage-policy implementation in C and Routed. Therefore C-vs-Routed does not intentionally grant Routed a different structural policy.

A causal numeric `Structural Saving` requires a separate no-skip ablation, for example:

```text
C-no-skip vs C
```

Unless that ablation is actually run, Phase 1 reports only:

- activated/skipped stage counts
- avoided model-call counts implied by policy
- which cases took each branch

It must **not** claim a measured structural token-saving percentage from C-vs-Routed alone.

## 1.5 Cost semantics

`estimated_cost_usd` is an **API-equivalent estimate**, not an assertion about the user's subscription invoice.

```text
estimated_cost_usd
  = provider_billing_adapter(normalized_usage, pricing_snapshot)
```

Reports must include the pricing snapshot date and source.

## 1.6 Aggregation

Saving percentages must not be averaged naively across cases.

For each level, use pooled totals:

```text
Saving_Ln = 1 - sum(Routed metric for valid Ln pairs)
                  / sum(C metric for valid Ln pairs)
```

For the overall primary result, use a micro/aggregate ratio across all valid pairs:

```text
Overall Routing Token Saving
  = 1 - sum(Routed tokens) / sum(C tokens)
```

Also report an equal-level macro summary:

```text
Macro Level Saving
  = mean(Saving_L1, Saving_L2, Saving_L3, Saving_L4, Saving_L5)
```

The micro result is the primary total-resource result. The macro result prevents long/high-level cases from completely hiding low-level behavior.

Every summary must show the valid-pair coverage, e.g. `15/15`.

## 1.7 Quality and operational columns

Token/cost savings are reported alongside, not instead of, quality.

Per case and aggregate reports include:

- success/failure
- deterministic test pass/fail
- review verdict as one of `PASS`, `FAIL`, or `NO_VERDICT` (a review call that produced no verdict line), with the per-attempt review history (`state.json` `review.history`: cycle, attempt, effort, verdict, failure type, escalation) joined on `run_id` — never re-parsed from review text. A typed `environment` failure and a `NO_VERDICT` review are counted separately from a code-quality `FAIL`: folding them into `FAIL` or dropping them charges reviewer-infrastructure faults to the model and would corrupt the G5 evidence
- retry count
- fix-loop tokens
- wall time
- final model/profile used per stage
- fallback count
- telemetry completeness

Phase 1 is a pilot/descriptive evaluation. It does not infer statistical non-inferiority from 15 cases. Savings and quality must remain separately visible in the report.

The phrase `quality-preserving` is allowed only when both conditions hold, and even then only descriptively:

1. Routed's final deterministic acceptance results are not worse than C's (no case that passes in C fails in Routed), and
2. the elevated/security case has no new failure under Routed.

Otherwise the report claims only token/cost saving, phrased as `N% token saving observed (quality metrics: ...)` without the quality-preserving qualifier.

---

# 2. Corpora

## 2.1 Routing Corpus — existing 100 cases

Purpose:

- routing accuracy
- level accuracy
- tier accuracy
- over/under routing
- executor-only token upper-bound/reference measurement

Existing tooling remains responsible for this cohort, including `eval_router_performance.py` and the current executor-only role of `eval_token_savings.py`.

Current distribution:

```text
L1: 12
L2: 25
L3: 20
L4: 20
L5: 23
Total: 100
```

The Routing Corpus is **not** used as the E2E execution average because many prompts do not have a compatible executable repository/test context.

## 2.2 Execution Corpus v1 — new 15 cases

The E2E corpus contains exactly 15 frozen cases:

```text
L1: 3
L2: 3
L3: 3
L4: 3
L5: 3
Total: 15
```

Allowed task types:

- `implementation`
- `local_refactoring`
- `architectural_refactoring`

Excluded from v1 E2E:

- design-only
- inspect-only
- review-only

These require different execution graphs and should be evaluated in separate cohorts if needed.

At least one L5 case must exercise the `elevated/security` path. This provides elevated-path coverage; with `n=1`, no independent elevated-tier average or statistical claim is made.

## 2.3 Case schema

Each case contains at least:

```yaml
name: string
gold:
  task_type: implementation | local_refactoring | architectural_refactoring
  level: L1 | L2 | L3 | L4 | L5
  tier: standard | elevated | critical  # only values supported by current router

task: string
fixture_dir: string
test_cmd: string
acceptance: string
```

The exact tier enum must match the repository's existing routing schema; the eval must not introduce a new tier vocabulary.

## 2.4 Fixture requirements

Each fixture is a small, self-contained repository.

Requirements:

- external network dependency: none
- deterministic local tests
- bounded file count/size suitable for repeated agent runs
- no dependence on user-global state
- reproducible install/setup
- task can be solved entirely from the fixture and task prompt
- C/B/Routed start from the exact same initial snapshot
- every run operates on a fresh copy

Security fixtures must model the relevant behavior locally. For example, an OAuth-refresh case may use local token-store/client/service modules and deterministic mocked provider behavior rather than a live OAuth provider.

## 2.5 Freeze rule

Before any live result is inspected, record all 15 cases in:

```text
evals/execution_corpus/CASES.md
```

After freeze:

- cases are not removed because they fail
- cases are not replaced because they produce inconvenient results
- gold metadata is not edited based on model behavior
- fixture bugs may be fixed only with an explicit corpus version/revision note and a complete rerun of affected comparisons

---

# 3. Instrumentation layer

## 3.1 Packaging decision

Use **Approach A: instrument the real pipeline**.

Do not create an eval-only fork of `pipeline.py`, and do not use a PATH shim.

Planned implementation footprint:

- small env-gated instrumentation path in the actual pipeline execution layer
- new `scripts/eval_e2e_pipeline.py` harness
- new provider usage parsers/adapters as needed
- new `evals/execution_corpus/` fixtures
- new pricing snapshot config
- focused unit/integration tests

## 3.2 Execution flow

```text
route file
   ↓
validate_argv()
   ↓
validated_route_argv
   ↓
[usage instrumentation enabled?]
   ├─ no  → execute validated argv unchanged
   └─ yes → instrument_execution_argv(validated_route_argv)
              ↓
            run_capture()
              ↓
            provider event parser
              ├─ raw trace (optional audit artifact)
              ├─ normalized usage record
              └─ logical assistant output
                         ↓
                   existing next pipeline stage
```

Instrumentation occurs **after route argv validation**.

## 3.3 Route integrity boundary

The route artifact remains unchanged.

- route schema/version stays at the current version (`v7` if that is still current at implementation time)
- route-file canonical argv does not contain telemetry flags
- validation semantics do not expand merely for eval telemetry
- telemetry flags are trusted constants defined in provider adapter code
- task text, env values, or route-file contents cannot inject arbitrary telemetry argv

Core invariant:

```text
strip_instrumentation(execution_argv) == validated_route_argv
```

Allowed transformations are exact provider-owned constants, for example:

```text
Codex: structured JSON event output flag
Claude: stream-json output flag (Phase 2)
```

The adapter controls the exact insertion position required by each CLI; do not assume blindly appending flags is valid.

## 3.4 Environment contract

Separate enablement from the sink path:

```text
MODEL_EFFORT_ROUTER_INSTRUMENT_USAGE=1
MODEL_EFFORT_ROUTER_USAGE_JSONL=<harness-created path>
```

Rules:

- the enable variable is boolean only
- the sink path is used only as an output destination
- neither value is converted into model CLI argv
- the harness creates/owns the run directory and sink path

This avoids using an env string as an argv injection surface while still allowing isolated per-run output.

## 3.5 Logical output preservation

Structured provider output must never leak into downstream model prompts.

The parser separates:

```text
raw structured stdout
  ├─ provider events / usage
  └─ logical assistant output
```

Only the logical assistant output is returned to the existing pipeline stage boundary.

With instrumentation disabled, command construction and logical-output behavior must follow the legacy code path unchanged.

## 3.6 Normalized usage record

Minimum record shape:

```json
{
  "run_id": "...",
  "case_id": "...",
  "mode": "c|routed|b",
  "stage": "classifier|planner|executor|reviewer|fix|...",
  "attempt": 1,
  "provider": "openai",
  "model": "...",
  "effort": "...",
  "input_tokens": 0,
  "cached_input_tokens": 0,
  "cache_write_tokens": 0,
  "output_tokens": 0,
  "reasoning_tokens": 0,
  "total_tokens": 0,
  "usage_status": "complete|partial|missing",
  "exit_code": 0,
  "wall_time_ms": 0
}
```

`provider` names the **billing/pricing namespace** the record's cost is computed in — `openai` for Phase 1 — not the execution adapter or CLI name. `codex` is the adapter whose argv and event stream the parser understands (the adapter key inside `e2e_usage`), while pricing is selected per provider, so Task 7 keys its snapshot on `provider` and the value is frozen before any pricing work begins. An `executor`/adapter field is deliberately not added until something needs to tell adapters apart within one provider.

`cached_input_tokens`, `cache_write_tokens`, and `reasoning_tokens` may be subsets or separately billed quantities depending on provider. Provider adapters must normalize semantics and compute `total_tokens` without double counting.

Usage belongs to the **invocation**, not to a single turn. When one invocation reports usage on several turns, each field is the sum over the turns that reported it — a field is never taken from a turn that did not report it — and the invocation counts as `complete` only when every usage-bearing turn carried both input and output. A partial turn is therefore sticky within its invocation, rather than promoted to `complete` by an earlier complete one (the implementation and its tests live in `scripts/e2e_usage.py`). **Verify this premise against a real CLI trace at Task 10**: compare the raw JSONL, the provider's own reported usage, and `e2e_usage.py`'s record on one smoke run. If the provider turns out to emit cumulative snapshots rather than per-turn usage, summing would double count and the rule must be replaced before the benchmark is gated.

## 3.7 Provider parser interface

Phase 1 implements Codex/OpenAI only.

The interface should nevertheless isolate provider-specific parsing so Phase 2 can add Claude Code without changing E2E aggregation logic.

Before the live corpus run, execute two Codex smoke cases to freeze the observed structured-event usage shape and the final logical-result event behavior for the installed CLI version.

---

# 4. Experiment matrix

| Dimension | C — Fixed-Ceiling | Routed |
|---|---|---|
| Runtime classifier | No | Yes; included in usage/cost |
| Metadata source | Frozen gold | Runtime classified result |
| Stage-policy implementation | Same production policy | Same production policy |
| Actual stage graph | Policy(gold) | Policy(classified) |
| Stage model/profile | Role/stratum `highest_allowed_profile(gold)` | Routed profile |
| Deterministic test | Same | Same |
| Retry/fix policy | Same | Same |
| Payload limits | Same | Same |
| Fixture initial snapshot | Same | Same |
| Timeout/resource policy | Same | Same |

Important interpretation:

- If `gold != classified`, Routed follows the classified path. That divergence is part of the measured router behavior.
- C remains an oracle-metadata fixed-ceiling reference and does not pay classifier cost.
- The same structural stage-policy implementation is used in both modes. A classification error that activates the wrong policy branch is a routing effect.
- Standalone structural-saving percentages require a separate no-skip ablation and are not inferred from this matrix.

## 4.1 B matrix

B is intentionally a different, simpler workflow:

```text
fixed executor ceiling
      ↓
deterministic test
      ↓
pass → done
fail → fixed-policy retry/fix → retest ...
```

B does not contain classifier/planner/reviewer calls. It is therefore a **system baseline**, not a routing-only baseline.

---

# 5. Cost adapter

## 5.1 Pricing snapshot

Use a version-controlled static pricing snapshot:

```text
config/model-pricing.json
```

Minimum structure:

```json
{
  "snapshot_date": "YYYY-MM-DD",
  "currency": "USD",
  "sources": {
    "openai": "official provider pricing page"
  },
  "providers": {
    "openai": {
      "<model>": {
        "input_per_million": null,
        "cached_input_per_million": null,
        "cache_write_per_million": null,
        "output_per_million": null,
        "reasoning_billing": "included_in_output|separate|not_billed"
      }
    }
  }
}
```

Rates that a provider does not use may be null/omitted; the adapter defines provider semantics.

The snapshot is filled from official provider pricing immediately before the benchmark and committed with the benchmark configuration/report.

Live price lookup is not used during a benchmark run.

## 5.2 Billing adapter semantics

The pricing adapter must understand provider usage semantics rather than blindly multiply every usage field.

For providers where cached input is a subset of total input, conceptually:

```text
uncached_input = input_total - cached_input
```

and cached tokens receive the cached-read rate rather than being billed twice.

Similarly, reasoning/thinking tokens are not automatically added to output cost. The adapter follows the provider's documented billing rule indicated by `reasoning_billing`.

Raw normalized usage is retained so a historical run can be re-priced with a later snapshot without rerunning the model.

## 5.3 Reporting language

Use:

```text
Estimated API-equivalent cost
Estimated API-equivalent cost saving
```

Do not label these values as actual subscription charges.

---

# 6. Harness and reporting

## 6.1 Harness

Create:

```text
scripts/eval_e2e_pipeline.py
```

Initial interface:

```text
--mode c|routed|b
--case <case-id>        # optional filter
--live                  # default is dry-run
```

Dry-run must validate fixture discovery, commands, paths, metadata, pricing config, and expected run layout without invoking live model calls. For C and B, dry-run also validates stage-policy resolution (their stage graphs derive from frozen gold metadata, so they are fully resolvable offline). For Routed, dry-run validates the classifier/routing **configuration** and graph construction paths, but it does not claim the actual Routed stage graph, because that graph is determined by runtime classification during a live run.

The harness owns:

- isolated run directory
- fresh fixture copy per run
- run/case/mode identifiers
- usage JSONL sink
- raw trace location
- stdout/stderr artifacts
- test output
- summary JSON
- failure artifacts

## 6.2 Run directory

Suggested shape:

```text
runs/e2e-token-savings/<timestamp>/
  metadata.json
  <case-id>/
    c/
      usage.jsonl
      summary.json
      test.log
      raw/
    routed/
      ...
    b/
      ...
```

A repository-appropriate ignored temp/output root may be used instead; the report records the actual artifact location.

## 6.3 Case-level summary

Each run summary records at least:

- frozen case metadata
- resolved stage graph
- stage profiles
- token totals by stage
- estimated cost by stage
- total token/cost
- test result
- review verdict, when present
- retry/fix count
- fallback count
- wall time
- usage completeness
- process exit status
- infrastructure/task failure classification

## 6.4 Aggregate report

Generate:

```text
docs/<date>-e2e-token-savings.md
```

Primary E2E tables contain:

```text
B | C | Routed
```

with token and cost reported separately.

A appears only as a clearly separated reference if it was measured against the same Execution Corpus under a defined A mode. Existing 100-case Routing Corpus executor-only numbers must not be inserted into the E2E table as if they were directly comparable.

Report sections include:

- overall C vs Routed routing savings
- overall B vs Routed system savings
- L1-L5 breakdown
- per-stage token/cost composition
- retry/fix contribution
- success/test/review outcomes
- stage skip counts
- classification mismatch cases
- valid-pair telemetry coverage
- pricing snapshot date/source
- provider/CLI version
- known limitations

---

# 7. Validation strategy

## 7.1 Unit tests

### Codex usage parser

Use checked-in representative JSONL fixtures captured from the agreed smoke runs.

Test at minimum:

- successful result
- usage extraction
- cached-token extraction
- reasoning-token extraction where present
- final logical assistant output extraction
- malformed event tolerance
- partial/missing usage classification

### Pricing adapter

Test at minimum:

- uncached input
- cached input without double charging
- optional cache-write billing
- output billing
- reasoning included-in-output behavior
- separate-reasoning behavior for future providers
- unknown model/rate failure is explicit, never silently zero

### argv instrumentation invariant

For every supported provider path:

```text
strip_instrumentation(instrument_execution_argv(validated)) == validated
```

Also verify no non-constant telemetry arg can be introduced.

### Fixture acceptance

Every execution fixture must prove:

- clean initial state has the expected precondition
- test command is deterministic
- acceptance tests actually detect the target defect/change
- external network is not needed

## 7.2 Smoke validation

Before the 15-case live experiment:

1. run two small live Codex structured-output cases
2. verify observed event schema
3. verify usage completeness
4. verify logical output reconstruction
5. freeze parser fixture(s)
6. run one end-to-end eval case in C and Routed mode before the full corpus

## 7.3 Instrumentation-off regression

With usage instrumentation disabled, use mocked/fixed subprocess output to verify:

- generated argv is exactly the legacy argv
- logical returned output is byte-identical for the same subprocess bytes
- exit-code propagation is unchanged
- stderr handling is unchanged

Do not use nondeterministic live model text as a byte-identity regression oracle.

---

# 8. Error handling and validity

## 8.1 Never silently drop a frozen case

A failed task remains an observation.

Examples:

- model returns bad code
- deterministic tests fail
- reviewer rejects
- normal policy retry is exhausted
- classifier falls back

If telemetry is complete, these are valid measurements and their consumed tokens/cost are included.

## 8.2 Separate execution failure from telemetry failure

Use distinct states.

### Execution failure

The task/pipeline fails but usage telemetry is complete.

- include token/cost
- include failure in quality metrics
- preserve all artifacts

### Telemetry partial/missing

A model invocation occurred but complete usage cannot be recovered.

- preserve partial raw data
- mark the run `telemetry_invalid` for primary token/cost KPI
- do not silently treat missing tokens as zero
- do not remove the frozen case from the report
- report valid-pair coverage explicitly

For C-vs-Routed routing KPIs, a pair is primary-metric-valid only when both sides have complete required telemetry.

If the cause is an instrumentation/parser defect, fix the measurement system and rerun the **entire affected comparison pair from fresh snapshots**, retaining the invalid attempt as audit history. Do not replace only the side with the inconvenient result.

## 8.3 Timeout and provider failure

Timeout/provider failure is recorded as an execution outcome.

If the provider emits complete usage before failure, include it normally. If usage is only partial, retain it as a diagnostic/lower-bound field but do not promote it to a complete primary-cost measurement.

Harness-level infrastructure retries must be distinguished from the pipeline's normal retry/fix policy.

## 8.4 Classifier fallback

Classifier fallback is part of Routed behavior.

- include its tokens/cost
- record the fallback reason/path
- do not substitute gold metadata merely to keep the run alive unless production policy itself does so

---

# 9. Phasing

## Phase 1 — Codex pilot

Scope:

- provider: Codex/OpenAI only
- Execution Corpus: frozen 15 cases
- modes: C + Routed + B
- 15 runs per mode
- **45 benchmark pipeline runs total**, excluding smoke/validation runs
- token, estimated API-equivalent cost, success, retry/fix, review, wall time

Execution order:

1. complete/freeze fixtures
2. validate pricing snapshot
3. run Codex structured-output smoke cases
4. validate parser and instrumentation invariants
5. execute C vs Routed first (30 runs), as **adjacent per-case pairs**
6. execute B secondary baseline (15 additional runs)
7. generate aggregate report

Run-order freeze (order/cache bias control):

- Each case runs as an **adjacent pair**: `pair(c) = [C(c), Routed(c)]`.
- The first-run mode inside each pair is counterbalanced from a frozen seed so the 15 cases split C-first 8 / Routed-first 7 (deterministic, recorded in the freeze document before any live run).
- B runs for all 15 cases in one batch after the C/Routed phase.
- The report records, per case and per mode, actual start order and `cached_input_tokens` share (observed cached-input share), so cost sensitivity to provider cache can be inspected directly.
- Divergence from the frozen order (a resumed/aborted run) is recorded, never silently reordered.

A is not required as a Phase 1 Execution Corpus mode. Existing executor-only A-style measurements remain a separate reference unless an explicit same-fixture A run is later added.

## Phase 1.5 — Confirmation expansion

Expand to approximately 30 execution cases if the pilot shows material variance/outlier sensitivity or if stronger confirmation is needed.

The added cases are defined and frozen **before** inspecting their live benchmark results.

Do not retroactively rebalance v1 based on which cases made the router look better or worse.

## Phase 2 — Claude Code adapter

Reuse the same frozen Execution Corpus and aggregation logic.

Add only provider-specific pieces:

- structured-output instrumentation
- event parser
- usage normalization
- billing semantics/pricing snapshot

This phase tests whether the observed routing effect generalizes across provider/tooling boundaries without mixing provider variation into the Phase 1 pilot.

---

# Implementation impact summary

Expected new/changed areas:

```text
scripts/pipeline.py                         # small env-gated instrumentation hook
scripts/eval_e2e_pipeline.py                # new harness
config/model-pricing.json                   # versioned pricing snapshot
evals/execution_corpus/CASES.md             # frozen manifest
evals/execution_corpus/<case>/...           # fixture repos/tests
tests/...                                   # parser/pricing/argv/fixture tests
docs/<date>-e2e-token-savings.md            # generated benchmark report
```

Exact filenames should follow the repository's current layout if equivalent modules already exist.

---

# Non-goals for Phase 1

- proving statistical significance from 15 cases
- comparing Codex vs Claude performance
- live provider price lookup during the benchmark
- changing route schema/version merely for telemetry
- treating API-equivalent cost as actual subscription billing
- attributing stage-skip savings to dynamic model routing
- measuring design-only/inspect-only/review-only tasks in the same execution cohort
- silently excluding failed or expensive cases

---

# Acceptance criteria for implementation

The Phase 1 implementation is ready for the live 15-case benchmark when all of the following hold:

1. Execution Corpus v1 contains exactly 15 frozen deterministic fixtures, L1-L5 three each, with at least one elevated/security L5 path.
2. C uses frozen gold metadata, no classifier, the production stage policy, and role/stratum ceiling profiles.
3. Routed uses the real classifier/routing/fallback path and includes all model-stage usage.
4. B uses no classifier/planner/reviewer and uses the defined executor-ceiling + deterministic-test/retry workflow.
5. C/B/Routed always start each case from the same fixture snapshot.
6. Instrumentation is injected only after route argv validation and can be stripped back to the exact validated argv.
7. With instrumentation disabled, legacy argv/output behavior is unchanged under deterministic mocks.
8. Codex structured output is parsed into complete normalized usage and the original logical assistant output.
9. Missing/partial usage is never silently treated as zero.
10. Pricing uses a committed official-source snapshot and provider-specific billing semantics without cached/reasoning double counting.
11. Per-level and overall pooled token/cost savings are reported with valid-pair coverage.
12. Quality/retry/wall-time metrics remain visible next to savings metrics.
13. Phase 1 report clearly labels cost as API-equivalent estimated cost.
14. The first full run consists of 30 C/Routed runs followed by 15 B runs, for 45 benchmark runs total, excluding smoke runs.

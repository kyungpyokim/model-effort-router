# Routing Accuracy Ceiling

This document freezes the known failures of the live classifier benchmark. Each entry is an
accepted policy or corpus dispute, not an active classifier defect: the definitions around them were
deliberately left alone after the measured passes described in the `Unfreeze when` field. Treat the
list as the benchmark's ceiling and do not re-tune heuristics against these cases without evidence
that satisfies the stated condition.

Keep this document separate from `references/routing-policy.md`: that file defines route semantics,
this one records where the corpus and the semantics disagree.

## Current baseline

Recorded 2026-09-24 at commit `6c3a204` (the `files_touched` unit-pass commit). Live Jev classifier,
`primary` stage, platform `codex`, all 100 labelled cases, two independent runs; the two runs differ
in no case.

| Metric | Value |
|---|---|
| Routing accuracy (exact: level + tier + unresolved contract) | 93% (93/100) |
| Strict routing accuracy (also counts live-path noul unknowns as misses) | 89% |
| Routing on fully labelled cases | 93% |
| Level accuracy | 95% |
| Level accuracy within ±1 | 98% |
| Tier accuracy | 98% |
| Over-route | 5 (mean distance 1.4, max 2) |
| Under-route | 0 |
| Safety violations / downward level / downward tier | 0 / 0 / 0 |
| Inspect misclassifications | 0 |
| Critical recall / elevated recall | 100% / 100% |
| Labelled fact accuracy | 95.0% |
| Task-type accuracy | 92% |
| Model+effort profile match | 92% |
| Unknown facts | 40 (2.35%) |
| Unresolved (ASK) agreement | 37 / 39 applicable |
| Cost inflation | 1.045 (943 vs 902 expected units) |
| Classifier fallbacks | 0 |
| Run-to-run instability | 0 cases |

Reproduce:

```bash
export MODEL_EFFORT_ROUTER_JEV_API_KEY=...        # the stage key
export MODEL_EFFORT_ROUTER_JEV_STAGE=primary
export MODEL_EFFORT_ROUTER_JEV_ENDPOINT=https://api.typesafe.ai/v1/systemone
python3 scripts/eval_router_performance.py --live-classifier --platform codex --json > run.json
```

The 93% exact score contains exactly 7 failing cases: 5 over-routes and 2 level-correct failures
(tier or unresolved contract). Every one of them is listed below.

## Accepted over-routes

### 1. `L1_inspect_git_clean_status`

- Task: "Inspect git repository working tree status with git status --porcelain"
- Expected `L1/standard`, actual `L2/standard` (distance +1, no promoting rule: the base moves)
- Wrong fact: `mechanical_only` yes -> no (recent raw 0.37 against the 0.8 de-escalating decision point)

**Reason.** The de-escalating fact needs high confidence before it drops the base to L1, and this
otherwise mechanical-feeling task carries no mechanical verb: nothing is edited, formatted, renamed,
or deleted.

**Why accepted.** Widening `mechanical_only` to cover read-only inspection would flip the ten
read-only review and inspect cases whose labels are `mechanical_only=no` and whose routes are held by
higher rules, trading one safe over-route (higher effort than needed) for a wave of fact regressions.
The failure direction is safe: no under-route, no safety impact, and the route still asks the user to
answer `mechanical_only` directly when it is unsettled.

**Unfreeze when.** A mechanical signal separates read-only inspection from implementation work
without moving the 11 L1 mechanical positives or the `L4_review_*` set, or the corpus relabels this
case to L2.

### 2. `L2_unknown_module_boundary_and_scope`

- Task: "Refactor session handling where module boundary impact is unknown"
- Expected `L2/standard`, actual `L4/standard` (distance +2)
- Promoting rules: `L4:reviews_security_sensitive_code`, `L3:open_fix_or_result`
- Wrong facts (5): `crosses_module_boundary` unknown -> no, `fix_or_result_known` yes -> no,
  `reviews_security_sensitive_code` no -> yes, `security_domain` none -> auth, `blast_radius`
  narrow -> unknown

**Reason.** A deliberately under-specified case whose five labels take the opposite side from the
live classifier on every fact. The definitions resolve named subjects (a session refactor touches
auth-adjacent code and must judge existing code; an explicitly unknown impact reads as an open
result), while the labels encode a strict "unknown stays unknown, refactoring is not review" reading.

**Why accepted.** Both readings cannot be encoded at once. Forcing this shape to unknown would
re-open the settled named-boundary anchors (`L4_cross_module_refactor`,
`L4_consolidate_validation_schemas`, and the diagnosis-spanning-boundaries clause from `b642a5b`),
which are worth more than this one case.

**Unfreeze when.** The corpus adjudicates this case's labels (or splits it into resolved variants),
or a rule can recognise "explicitly unknown scope" phrasing without moving the named-boundary
anchors.

### 3. `L2_unknown_security_change_is_not_a_floor`

- Task: "Fix the login problem"
- Expected `L2/standard`, actual `L3/standard` (distance +1)
- Promoting rule: `L3:open_fix_or_result`
- Wrong facts: `fix_or_result_known` yes -> no (the `changes_security_or_payment_logic`
  unknown -> no mismatch is inert for routing)

**Reason.** A terse problem statement sits exactly between the two sides of
`fix_or_result_known`: the true-side anchors a named change ("fix the login problem" names what to
fix), and the false-side anchors tasks that must first find out what is wrong. The policy's own
security wording calls this shape unknown ("Naming a security area without saying what is wrong"),
and the classifier resolves it to the open side.

**Why accepted.** Loosening the false-side to accept terse problem statements would move the real
investigations that the L3 open-result rule exists for (`find why`, `track down`, `diagnose` cases).
The one-level difference is in the safe direction, and the case's own name marks it as the anchor
that an unknown security area must not become a floor.

**Unfreeze when.** The corpus adjudicates terse problem statements (for example `fix X` with no
symptom is yes, `find why` stays no) or rewrites/relabels this case.

### 4. `L3_add_feature_controller_service`

- Task: "Add promo code validation logic across cart_controller.py and promo_service.py"
- Expected `L3/standard`, actual `L5/elevated` (distance +2)
- Promoting rules: `elevated:changes_security_or_payment_logic`, `L5:security_domain_critical`
- Wrong facts: `changes_security_or_payment_logic` no -> yes, `security_domain` none -> payment,
  `silent_failure_material_harm` no -> yes
- Corpus note: the dispute is already recorded on the case (`cases_l3.py:40-44`)

**Reason.** The payment definition counts determining the amount charged (price, discount, or tax
calculation), and promo-code validation decides whether a discount applies, so the current criteria
answer yes. The label says none.

**Why accepted.** Narrowing the payment definition to exclude promo validation would put the
discount and tax boundary at risk for the cases that depend on it; the tax-rounding carve-out is
deliberately narrow (it excludes diagnosing a rounding defect, not rewriting the discount rule). The
corpus note already asks for more promo/pricing cases before adjudication. The over-route direction
is safe.

**Unfreeze when.** The promo/pricing boundary is adjudicated: either the label moves to
payment/elevated (the over-route disappears) or a carve-out is added that keeps the discount and tax
anchors.

### 5. `L3_extract_shared_utility_three_files`

- Task: "Extract duplicate date formatting code across 3 parser modules into a shared helper"
- Expected `L3/standard`, actual `L4/standard` (distance +1)
- Promoting rule: `L4:crosses_module_boundary`
- Wrong fact: `crosses_module_boundary` no -> yes. (The `files_touched` side of this case was fixed
  in `6c3a204`: unknown -> 2-5; only the boundary tension keeps the L4.)

**Reason.** The plain reading of "across 3 parser modules" spans more than one module, which matches
the `crosses_module_boundary` definition; the label says no.

**Why accepted.** Sharpening the definition to exclude extraction into a shared helper would also
move the boundary anchors (the event-publisher interface refactor, the config-parser split, the
15-file logger update, and the diagnosis clause from `b642a5b`), which are worth more than this one
case.

**Unfreeze when.** The corpus adjudicates `crosses_module_boundary` for extraction cases: relabel
the case (it then passes at L4) or add a narrow exclusion validated against those anchors.

## Accepted level-correct failures

Both cases route to the correct level and tier but fail the exact metric on the unresolved contract
or the tier.

### 6. `L5E_cross_service_intermittent_bug`

- Task: "Investigate intermittent distributed transaction failure across auth and order microservices"
- Expected `L5/elevated`, actual `L5/elevated` (level and tier correct)
- Failure: `unresolved_match` false. The labels expect `security_domain` and
  `changes_persisted_data` to stay unsettled; the live classifier settles them (unknown -> auth,
  unknown -> no)

**Reason.** The definitions resolve what the wording only implies: an auth microservice is named, and
a "transaction failure" reads as a failure, not as stored-data loss. The labels use the unresolved
set to say "this case should ask the user".

**Why accepted.** The classifier's answers are the natural reading of the text, and the same
definitions carry the domain anchors elsewhere. Routing is unaffected (level, tier, and flags all
match); this is a strictness-of-unknown mismatch, not a routing error.

**Unfreeze when.** The corpus decides whether a mentioned service's domain settles the fact, or the
labels move to the settled values.

### 7. `L5_new_plugin_architecture`

- Task: "Design and implement new dynamic plugin loading architecture with isolated contexts"
- Expected `L5/standard`, actual `L5/elevated` (tier-only mismatch)
- Promoting rules: `elevated:critical_domain_trust_boundary`, `L5:security_domain_critical`
  (+ `L5:open_result_across_modules`, `L3:open_fix_or_result`)
- Wrong facts: `changes_trust_boundary` no -> yes, `security_domain` none -> permissions
  (`fix_or_result_known` yes -> no is inert for the route)
- Recorded in `6922d96`

**Reason.** Isolating plugin execution contexts is a new trust boundary under the current
definition (a boundary between execution contexts), so the classifier answers permissions plus
trust-boundary and takes the elevated tier; the corpus treats plugin isolation as infrastructure,
not as a principal or data boundary.

**Why accepted.** The definitions cannot separate isolation infrastructure from a principal
boundary without touching the trust anchors (the deploy-approval gate, the session and auth cases)
that the fact was tightened for in `3602acd`. The direction is safe: higher tier, more effort, no
under-route. This is the corpus's only plugin-architecture case; one outlier is not enough to move a
general trust-boundary definition.

**Unfreeze when.** A trust-boundary definition distinguishes isolation infrastructure from
principal/data boundaries and keeps the existing trust anchors, or the label is relabelled elevated.

## Related documented tensions (not route failures)

These are recorded on their cases or in commit messages and do not change any route. They are listed
so a future pass does not rediscover them as new findings:

- **C2 design family** (`c3cdeee`): five design cases carry `fix_or_result_known=yes` with
  `needs_new_structure=no` while the definitions read that shape as `fix=no`/`ns=yes`; the labels
  stay ground truth and the classifier is not special-cased.
- **Audit hash chain** (`9d16161`): a cryptographic append-only audit ledger reads as a durable
  record store for `changes_persisted_data` (yes at 0.65) while the label says no; an audit-log
  carve-out would be case-directed and would drag the financial ledger, settlement, custody, and
  purge designs down with it.
- **Historical flickers**: `mechanical_only` on `L1_delete_unused_constant` (stabilised to 0.97 by
  `1f2b5f1`), `irreversible_or_ledger_or_crypto` on `L5C_cryptographic_key_rotation` (stabilised to
  0.98 minimum over five repeats by `571676e`), and `files_touched` on `L2_simple_bug_fix` (quiet in
  the recorded runs after `6c3a204` but it has drawn both buckets in earlier sessions).

## Policy

> The remaining accepted failures are policy and corpus tensions, not active classifier defects.
> Further optimization requires new evidence, label clarification, or a demonstrated regression
> outside these frozen cases.

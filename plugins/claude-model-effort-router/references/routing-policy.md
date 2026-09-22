# Model Effort Router Policy (v5)

## Overview

The Model Effort Router classifies coding tasks by difficulty and risk, routing them to a matching model and reasoning-effort profile. The v7 route schema uses a 5-level scale (`L1` through `L5`) plus a separate **risk tier** (`standard`, `elevated`, `critical`; route JSON field `risk_tier`), one bounded same-model lookup (then a question to the user) when a fact is unknown, and deterministic Python mapping. The former L6, L7, and Critical Override levels no longer exist: their intent lives on as the `elevated` and `critical` tiers, which imply L5 and raise the effort of the planning/judging stage only.

## Classification Architecture

The classifier answers facts; code decides the level. There are no difficulty scores
and no self-reported confidence.

```text
User Request
     │
Classifier (Luna Low / Sonnet / Gemini 3.8 Flash Med, or the in-session difficulty-assessor agent)
  -> task_type + 17 facts (yes / no / unknown, plus a security domain and blast radius) + evidence
     │
DIFFICULTY_RULES (scripts/router.py)
  ├─ Base L2 (L1 when mechanical_only = yes)
  ├─ Highest matching rule wins; an elevated/critical rule -> L5 + that risk tier
  └─ "unknown" matches no rule: it never raises the level, tier, or flags
     │
Facts still unknown -> ONE bounded read-only lookup by the same classifier (never a stronger model)
  -> anything left is reported as unresolved_facts + questions and the user is asked (exit 3, or a terminal prompt)
     │
Risk floors (Security/Payment change or critical-domain trust boundary -> elevated tier, critical security domain -> L5, security review -> L4, Migration/Public API -> L4) -> Matrix lookup (task_type × level)
     │
Apply risk tier: raise the planning/judging stage (elevated = xhigh, critical = max; Antigravity swaps to Claude Opus Thinking)
```

The classifier returns structured JSON with `task_type`, `facts`, `delegability` (0–2), up to five `evidence` strings, and a one-sentence `reason`. The classifier applies a `readchk` reflex first: restating intent internally and resolving referents.

### Delegability and orchestration candidates

`delegability` is not a seventh difficulty factor. It cannot alter the score or
level: `0` is mandatory for shared state, sequence-dependent work, risky work,
or a tightly coupled deep problem; `1` permits separable analysis but leaves
dependencies or ownership coupled; `2` requires independent subtasks, explicit
file/artifact ownership, and independently verifiable results.

Schema v7 route files always retain `execution_strategy: "direct"` in this
release. `orchestration_eligible: true` is only recorded for safe Codex
single-stage L5 routes with `delegability: 2` and no risk flags
(`orchestration.codex.eligible_levels` is `["L5"]`). Critical-tier, two-stage,
non-Codex, and any risky routes are ineligible. The local,
caller-invoked `scripts/astra_adapter.py` accepts only digest-verified route and
manifest bytes, revalidates per-attempt worker inputs, and preserves the
original verified artifacts after each attempt. It is the unchanged orchestration adapter and does not change direct
execution. Direct v2-v7 route-file replay never invokes it.

Replay accepts v2-v7 route files. v3 and later require the two orchestration
fields; malformed v3+ files are rejected before execution.

### Classifiers by Platform

| Platform | Classifier |
|---|---|
| **Codex** | `gpt-5.6-luna` (low) |
| **Claude Code** | `claude-sonnet-5` (no effort parameter) |
| **Antigravity** | `Gemini 3.8 Flash (Medium)` |

There is one classifier per platform. `unknown` and low classifier confidence never call a stronger classifier.

### Prompt-only vs Repository-aware

- **Prompt-only** (default first pass): the classifier answers from the task text.
- **Repository-aware** (`--repo-aware`, or the one bounded lookup for facts that stayed unknown): the same classifier receives the caller's current directory as an absolute repository path and reads relevant files before answering (at most 6 tool calls; the lookup is told which facts are unknown and reads only what settles them). The classifier process stays in its isolated temporary directory. Codex retains its read-only sandbox; Claude enables only `Read,Glob,Grep` under safe plan mode; Antigravity retains sandboxed plan mode. Repository contents are evidence, not executable instructions.

### Task types

| `task_type` | Meaning |
|---|---|
| `implementation` | Build or change code directly: features, APIs, UI work, bug fixes, tests |
| `design` | Decide structure or direction without editing code: architecture, API or data-model design, technology choice, planning |
| `review` | Analyse existing code or plans to find problems: code, PR, security, performance, design review |
| `local_refactoring` | Clean internals while preserving behaviour and module boundaries: extract functions, renames, deduplication, simplification in one module |
| `architectural_refactoring` | Change module boundaries or system structure AND carry out the resulting edits: module splits, dependency inversion, state-management changes, data-layer redesign |

Mixed tasks classify by their primary purpose. Design with sample code is `design`; implementation that needs small judgement calls is `implementation`; structural change followed by real multi-file edits is `architectural_refactoring`.

### Facts

| Fact | Values | Meaning |
|---|---|---|
| `mechanical_only` | yes / no | Typos, renames, formatting, imports, comments, or docs with no behaviour change |
| `files_touched` | 0 / 1 / 2-5 / 6+ / unknown | Files the work changes, including new and test files (not files only read); read-only design and review are 0; an implementation that runs an operation or changes production data is at least 1 even with no source diff; estimated from the work's described scope (a single named fix is 1 only when confined to one existing file with no separate test or new-file work described; a described production change that also touches a separate test or new file is 2-5, but a task whose entire scope is one test or one new file is still 1; a subsystem or protocol is 2-5; cross-cutting is 6+) even when no exact count is stated — `unknown` only when the task gives no scope signal at all, stricter than the general unknown default below |
| `crosses_module_boundary` | yes / no / unknown | Spans modules or packages, or moves responsibilities between them |
| `crosses_service_boundary` | yes / no / unknown | Work or diagnosis spans services, processes, or repositories |
| `fix_or_result_known` | yes / no | The expected result or place to change is stated or evident, including choosing between explicitly named options; no when the goal or candidates must still be investigated or invented |
| `intermittent_or_concurrency` | yes / no / unknown | Only timing-dependent or concurrency defects (races, deadlocks, ordering, interleaved retries or distributed transactions); occasional slowness or failures without a stated timing aspect are no |
| `needs_new_structure` | yes / no | Only a new architecture, protocol, cross-module or cross-service boundary, or data-migration strategy designed with open choices; laying out files in one new module (including proposing the file layout for one new module inside an existing service) or moving code along a stated boundary is no |
| `changes_security_or_payment_logic` | yes / no / unknown | Auth, secrets, cryptography, or payment behaviour changes (mentions, moves, and review-only work do not count; reviews are covered by the two facts below); extracting an auth module into its own service with the same behaviour is no here — judged under `changes_trust_boundary` instead, since moving that code across a service boundary decides to move a trust boundary |
| `reviews_security_sensitive_code` | yes / no / unknown | The work reviews, audits, analyses vulnerabilities or attack paths in, or judges the correctness or safety of code or designs in a security-sensitive area (auth, permissions, secrets, cryptography, payment, personal data), whether or not code changes; authorization or permissions covers access boundaries: tenant isolation and customer-specific data isolation, including cache keys or namespaces that hold per-customer or per-tenant data (a wrong key can expose one customer's data to another) |
| `security_domain` | none / auth / payment / secrets / crypto / permissions / pii / unknown | The most critical security-sensitive area whose behaviour the work changes or whose correctness it judges (payment > crypto > auth > permissions > pii > secrets); `permissions` covers the access boundaries above (tenant isolation and customer-specific data isolation, including cache keys or namespaces that hold per-customer or per-tenant data; caching per-customer invoices is not payment but is a permissions review); `none` for mentions, renames, or docs, or a move within one trust zone; moved across a trust or service boundary keeps its domain, since `changes_trust_boundary` judges that move separately |
| `changes_public_api_contract` | yes / no / unknown | Externally consumed API, CLI, schema, or response format changes; a new endpoint consumed only by your own frontend, without changing existing external consumers or a published schema, is no |
| `changes_persisted_data` | yes / no / unknown | Stored data, database schema, or data migration changes; no when the task lists the files to change and none of them is a migration, schema, or repository/data-access file |
| `irreversible_or_ledger_or_crypto` | yes / no / unknown | Irreversible production data, ledger correctness, or designing new cryptographic algorithms/protocols/key-management (implementing or reviewing signing, verification, hashing, or token rotation with existing libraries is no; a schema or data migration that can be rolled back is no, as are retries, compensating transactions, idempotent re-runs, and other recoverable fixes) |
| `changes_trust_boundary` | yes / no / unknown | Designs, changes, or decides where trust is established or delegated between components, services, tenants, or principals (service-to-service auth, token propagation, permission delegation, isolation), including whether to move it; reviewing existing boundary code or moving code within one trust zone is no |
| `blast_radius` | narrow / broad / unknown | broad: a wrong result affects many services, all users or tenants, production data at large, external API consumers, or money/credentials system-wide; narrow: one component, feature, or a recoverable subset |
| `silent_failure_material_harm` | yes / no / unknown | A mistake could go unnoticed (no error, alert, or failing test) while causing data loss or corruption, wrong money movement, security exposure, or cross-service inconsistency |
| `requires_code_understanding` | yes / no / unknown | Doing the work right depends on reading and understanding existing code beyond the edit site (callers, callees, existing behaviour, invariants, state flow); no for a self-contained edit evident from the task text (a new standalone helper, an added field or parameter, a clear one-line change, a test for stated behaviour). It never changes the level: it only picks the L2 implementer (below). A classifier reply or stored classification that omits it defaults to `unknown` |

Payment, in `changes_security_or_payment_logic`, `reviews_security_sensitive_code`, and `security_domain`, is decided by monetary consequence, not by a module or file named billing or order: moving money; determining the amount charged (price, discount, or tax calculation); authorizing, capturing, cancelling, or refunding payments, including an order cancellation that decides a refund; ledger or settlement correctness; or creating or changing a monetary obligation. Not payment: an order list UI, billing address edits, displaying an invoice PDF, order status strings, order creation that charges nothing, or code that merely lives in a billing or order module. Caching or reading billing or order data is not payment unless the cached or read value decides the amount charged.

Authorization or permissions, in `changes_security_or_payment_logic`, `reviews_security_sensitive_code`, and `security_domain`, is decided by access control boundaries (user authentication, RBAC, ACL, privilege, tenant isolation, credentials, or customer data isolation). Two narrow carve-outs are NOT authorization, permissions, or security changes: cost/model-tier confirmations (approving an expensive model before it runs), and plain UX confirmations that do not decide whether an action is allowed. Everything else that decides whether an agent, tool, or command may run without the user's consent IS authorization/permissions: tool or command permission prompts, sandbox or allowlist rules for shell commands, production or deploy approval gates, and adding, removing, or bypassing any such gate.

### Difficulty Rules

The level is the highest matching rule over a base of L2 (L1 when `mechanical_only` is yes). Rules named `elevated` or `critical` set the **risk tier** and imply L5; the levels themselves stop at L5.

| Level / tier | Rule (all conditions must hold) |
|---|---|
| **critical** tier (L5) | `irreversible_or_ledger_or_crypto` = yes |
| **elevated** tier (L5) | `needs_new_structure` = yes, `crosses_service_boundary` = yes, `fix_or_result_known` = no (`new_structure_across_services_with_open_result`) |
| **elevated** tier (L5) | `security_domain` = payment, crypto, auth, permissions, or pii, `changes_trust_boundary` = yes (`critical_domain_trust_boundary`) |
| **elevated** tier (L5) | `changes_security_or_payment_logic` = yes |
| **elevated** tier (L5) | `intermittent_or_concurrency` = yes, `crosses_service_boundary` = yes (`intermittent_across_services`) |
| **L5** | `security_domain` = payment, crypto, permissions, or pii (bare auth has no L5 floor of its own) |
| **L5** | `needs_new_structure` = yes |
| **L5** | `intermittent_or_concurrency` = yes |
| **L5** | `fix_or_result_known` = no, `crosses_module_boundary` = yes |
| **L4** | `reviews_security_sensitive_code` = yes |
| **L4** | `crosses_module_boundary` = yes |
| **L4** | `crosses_service_boundary`, `changes_public_api_contract`, or `changes_persisted_data` = yes |
| **L4** | `files_touched` = 6+ |
| **L3** | `files_touched` = 2-5 |
| **L3** | `fix_or_result_known` = no |

Security floors follow the impact of a wrong judgement, not whether code is edited: a review-only task in a security-sensitive area (`reviews_security_sensitive_code` = yes) floors at L4 independent of `task_type`, and a bare `security_domain` of payment, crypto, permissions, or pii floors at L5. Bare auth has no L5 floor; confirmed auth changes reach the elevated tier and auth reviews reach L4. `secrets` alone has no floor of its own; it reaches L4 through the review fact or the elevated tier through the change fact. These are floors: they never lower a higher matching rule or the critical tier.

The elevated and critical tiers follow the impact of a wrong judgement; `task_type` and whether code changes never lower them. A critical `security_domain` whose trust boundary changes is elevated. `needs_new_structure` is a design-difficulty signal, not a tier signal by itself: a new structure across services with an open result is elevated, while new structure alone is L5.

### Risk tiers

| `risk_tier` | Level | Effect |
|---|---|---|
| `standard` | any | Matrix row unchanged |
| `elevated` | L5 | Planning/judging stage effort raised to **xhigh** (Codex Sol, Claude Code Opus); Antigravity swaps that stage to Claude Opus Thinking |
| `critical` | L5 | Same stage raised to **max**; Antigravity swaps to Claude Opus Thinking; never orchestration-eligible |

The raised stage is the planner of a two-stage route, otherwise the only stage; the implementer keeps its matrix profile. Tiers only raise effort, never lower it. `--critical` forces the critical tier. `--level` accepts `L1`-`L5` only. Tier profiles live under `tiers` in `config/model-map.json`.

Unknown policy: `unknown` means the classifier lacks the information to answer yes or no. It is not difficulty and not risk, so `unknown != yes`, `unknown != high difficulty`, `unknown != high risk`, and `unknown != escalation`. An unknown fact never matches a rule (no floor, no tier, no risk flag) and never triggers a stronger classifier or a classifier retry. It is resolved in this order:

1. **One bounded read-only lookup** by the same classifier, limited to what settles the unknown facts. It may only fill a fact that is still unknown; a fact the first pass answered is never changed by it. A failed lookup leaves the first answer as it was.
2. **A question to the user** when intent, requirements, or context is missing, when the repository or file cannot be reached, or when the lookup still cannot settle a fact. The route JSON carries `unresolved_facts` and `questions`, the router exits `3` (a launcher stops before running a guessed route), and on a terminal it asks directly. `--answer FACT=VALUE` supplies an answer; it only fills a fact that is still unknown. A route with unresolved facts is not stored for session reuse.

`requires_code_understanding` (optional, defaults to `unknown`) is looked up like any fact but never asked: unknown only leaves the cheaper implementer rung.

### Risk Flags and Hard Floors

Risk flags are derived from facts: `changes_security_or_payment_logic` = yes sets `security_sensitive`, `changes_persisted_data` = yes sets `data_migration`, and `changes_public_api_contract` = yes sets `public_api_change`. Manual and pinned classifications may carry any of:

```text
security_sensitive   authentication      authorization
payment              data_migration      public_api_change
```

- Any of `security_sensitive`, `authentication`, `authorization`, or `payment` (when involving actual code/behavior changes) forces the **elevated** risk tier (which implies L5) and activates an Autobahn scope guard instruction. Non-security changes mentioning security terms (such as typo fixes or documentation edits) do not activate these flags and remain at their natural level (e.g. L1).
- An active `data_migration` or `public_api_change` forces a floor of **L4**. Floors do not stack: the risk factor already scores these risks.
- Review-only security work sets no risk flag (the elevated-tier change floor and the Autobahn scope guard belong to behaviour changes); its L4/L5 floors come from `DIFFICULTY_RULES` alone.
- **Critical tier**: irreversible data migration, mass production data deletion, financial ledger correctness, designing new cryptographic algorithms/protocols/key-management (`irreversible_or_ledger_or_crypto` = yes), or the explicit `--critical` argument sets `risk_tier: critical` (L5 with maximum planning/judging effort: Codex Sol max, Claude Code Opus max, Antigravity Claude Opus Thinking). Fires only on an explicit yes; an unknown never triggers it.
- Rules never drive difficulty on their own: the LLM classifies facts, and rules only guarantee a minimum for confirmed high-risk work. The keyword "security" alone never implies a level; `changes_security_or_payment_logic` = yes on a modifying task does. `unknown` != `yes`: unknown is missing information (settled by one bounded lookup or a question to the user, never a stronger classifier), not confirmed risk.

## Default Execution Model Map

### Codex Matrix

| task_type | L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|
| implementation | luna med | luna med (luna high with `requires_code_understanding`) | terra med | terra high | sol high → terra high |
| design | luna med | sol high | sol high | sol high | sol high |
| review | luna med | sol high | sol high | sol high | sol high |
| local_refactoring | luna med | luna med (luna high with `requires_code_understanding`) | terra med | terra high | sol high → terra high |
| architectural_refactoring | luna med | sol high | sol high → terra med | sol xhigh → terra high | sol xhigh → terra high |

### Claude Code Matrix

| task_type | L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|
| implementation | haiku | haiku (sonnet low with `requires_code_understanding`) | sonnet med | sonnet high | opus high → sonnet high |
| design | haiku | opus high | opus high | opus high | opus high |
| review | haiku | opus high | opus high | opus high | opus high |
| local_refactoring | haiku | haiku (sonnet low with `requires_code_understanding`) | sonnet med | sonnet high | opus high → sonnet high |
| architectural_refactoring | haiku | opus high | opus high → sonnet med | opus xhigh → sonnet high | opus xhigh → sonnet high |

### Antigravity Matrix

Antigravity uses `Gemini 3.8 Flash (High)` as its minimum execution floor:

| task_type | L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|
| implementation | Flash High | Flash High | Flash High | Sonnet Thinking | Pro High → Sonnet Thinking |
| design | Flash High | Flash High | Pro High | Pro High | Pro High |
| review | Flash High | Flash High | Pro High | Pro High | Pro High |
| local_refactoring | Flash High | Flash High | Flash High | Sonnet Thinking | Pro High → Sonnet Thinking |
| architectural_refactoring | Flash High | Flash High | Pro High → Flash High | Pro High → Sonnet Thinking | Pro High → Sonnet Thinking |

`A → B` marks a two-stage route: stage A plans, stage B executes. The tables above are the configured matrix; the router derives the plan stage for the code-change rows that are single-stage there.

**Plan-implement-review workflow.** Standard L1-L2 read-only `inspect` routes use Luna Low/Haiku alone. Every code-change route requires a deterministic test command; the launcher fails closed before a model runs when it is absent. A mechanical L1 code change uses the trivial-edit fast path only when `requires_code_understanding=no` and a deterministic check is configured; it skips plan and review, never the test. Every other code-change route uses the L2-or-higher judge rows for plan -> implement -> deterministic test -> merged review, and its review may re-plan. The judge floor is `WORKFLOW_MIN_LEVEL = "L2"` in `scripts/router.py`.

- **Fast Path is explicit.** An L1 code change without the trivial-edit gates gets the regular plan/review workflow. `inspect` stays read-only; risky, open-ended, or high-level inspect work is promoted to `review`.
- **The planner comes from the platform's `design` row at `max(level, L2)`** (Codex Sol, Claude Code Opus, Antigravity Flash/Pro per the table); the implementer keeps its matrix or refined rung. A single-stage matrix row therefore becomes `design-row planner → implementer`, and rows already written as `A → B` are used as they are.
- **Exception: planner equals implementer.** If the derived planner's (model, effort) equals the implementer's, no planner is inserted and the route stays single-stage, because a plan by the same model at the same effort buys nothing. That covers exactly: Codex and Claude Code `architectural_refactoring` at L2 (Sol high / Opus high), and every Antigravity L2 code-change route (`implementation`, `local_refactoring`, `architectural_refactoring`: Flash High both ways). Such a route still gets the non-fast review and re-plans with the reviewing judge. Because that judge is the same model as the implementer (Sol on Codex and Opus on Claude Code for `architectural_refactoring` at L2; the same Flash model on every Antigravity L2 code-change route), the review there is a self-review until reviewer separation lands (Phase 3).
- **Review from `WORKFLOW_MIN_LEVEL`.** Every non-fast code-change route gets the merged review by the platform's `review` row at `max(level, L2)`, after a green test run.

Effective code-change routes (standard risk; `implementation` and `local_refactoring` share a row; L1 is the single-stage matrix cell above):

| Platform | task_type | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|
| Codex | implementation / local_refactoring | sol high → luna med (luna high with `requires_code_understanding`) | sol high → terra med | sol high → terra high | sol high → terra high |
| Codex | architectural_refactoring | sol high (single) | sol high → terra med | sol xhigh → terra high | sol xhigh → terra high |
| Claude Code | implementation / local_refactoring | opus high → haiku (sonnet low with `requires_code_understanding`) | opus high → sonnet med | opus high → sonnet high | opus high → sonnet high |
| Claude Code | architectural_refactoring | opus high (single) | opus high → sonnet med | opus xhigh → sonnet high | opus xhigh → sonnet high |
| Antigravity | all three | Flash High (single) | Pro High → Flash High | Pro High → Sonnet Thinking | Pro High → Sonnet Thinking |

Risk tiers modify these rows at the planning/judging stages only (the planner and the reviewer of a code-change route, otherwise the single stage); the implementer never changes:

| Platform | `elevated` | `critical` |
|---|---|---|
| Codex | that stage's effort raised to `xhigh` | `max` |
| Claude Code | that stage's effort raised to `xhigh` | `max` |
| Antigravity | that stage swaps to `Claude Opus Thinking` | same |

- `Claude Opus Thinking` on Antigravity resolves availability-driven: `Claude Opus 5 .*(Thinking)` → `Claude Opus .*(Thinking)` → `Opus.*Thinking` → `Claude Opus 4.6 (Thinking)` (fallback).
- `Pro High` on Antigravity resolves availability-driven: preferred `Gemini 3.1 Pro (High)` → `Gemini .* Pro (High)` → `Claude Sonnet .* (Thinking)`.
- On Claude Code, `sonnet` is `claude-sonnet-5` (medium at L3, high at L4), `haiku` is `claude-haiku-4-5` without an effort parameter, and `opus` is `claude-opus-5`. On Codex, `luna`, `terra`, and `sol` are `gpt-5.6-luna`, `gpt-5.6-terra`, and `gpt-5.6-sol`.
- Effort ceilings: Luna low/medium/high (a task that needs more than Luna high moves to Terra, never to Luna xhigh); Terra medium/high; Sol high/xhigh/max (Sol and Opus never run design, review, or planning below high). Luna high and Sonnet low are routed only through the L2 refinement (`refinements` in the config, applied after the matrix lookup to single-stage `implementation` and `local_refactoring` routes at L2): `requires_code_understanding` = yes -> Luna high (Codex) / Sonnet low (Claude Code); no or unknown -> the matrix profile, Luna medium / Haiku. `unknown` is missing information, not evidence, so it keeps the cheaper profile; a failing test gate or the fix loop covers a wrong guess. L3 stays Terra medium / Sonnet medium and higher levels are unchanged. Antigravity defines no refinement. Reused session routes keep the stored fact. A refinement is keyed on the post-escalation level, so an explicit `--level L2` on a mechanical task can reach it. It replaces the whole matrix entry, so a refinement stage must carry its own `fallback_model` or `candidates` if the entry it replaces had them, and a refinement that lowers the same model's effort is refused.

## Execution roles and pipeline

Goal: spend top-model tokens on important judgement, and run already-decided work on the cheapest sufficient model.

- Codex: **Sol thinks, designs, verifies, and reviews; Luna and Terra implement and fix.**
- Claude Code: **Opus thinks, designs, verifies, and reviews; Haiku and Sonnet implement and fix.**
- Tests run in the launcher, with no model.
- Classification stays cheap (the configured classifiers above, unchanged).

The model comes from role + difficulty + risk, not difficulty alone: the same L4 maps to Sol/Opus for design, review, or verification and to Terra high / Sonnet high for implementation. Role maps onto the existing task types: design = planning/architecture (`design`), review = verification/review (`review`), and `implementation`, `local_refactoring`, and `architectural_refactoring` = implementation; every non-fast code change takes its plan and review stages from the `design` and `review` rows at `max(level, L2)` (see the workflow above).

```text
request
  -> cheap classifier (facts) -> route (task_type, level, risk_tier)
  -> plan (every non-fast code change) .... design-row judge      (once; Sol / Opus)
  -> implement ............................. route's implementer   (Luna / Terra / Haiku / Sonnet)
       new design problem found? STOP, return evidence -> re-plan
  -> deterministic tests ................... launcher, no model
  -> ONE verification + code review ........ review-row judge      High (elevated: XHigh, critical: Max)
       PASS -> done
       FAIL -> fix by the route's implementer -> tests -> review again (see fail loop caps)
```

The planned model-by-difficulty step routing (re-classifying each planned step and each review FAIL to pick a cheaper or stronger fixer) is not implemented yet; today every stage of a route uses the model the route names.

Rules:

- **Planning and implementation difficulty are separate.** A hard overall task (for example redesigning the router's security hard floor) is designed by Sol/Opus and implemented by the cheaper model the matrix picks for that level. The planner does not implement (except the planner == implementer rows above). Re-classifying each planned step is planned, not implemented.
- **Test execution** (pytest, lint, formatter, typecheck, build) is run by the launcher itself, with no model. The final verification ("does this satisfy the requirement?") is the Sol/Opus review.
- **Runtime enforcement.** `scripts/pipeline.py` runs the regular chain (launchers call it for every non-interactive run; interactive sessions stay a single hand-off). The route JSON (schema v7) holds only who does each role (`steps`, plus a `pipeline` block: `review`, `replan`, `limits`, `task`); where the run is (phase, fix and review counters) lives in `state.json` in the run's work directory, never in the route. Role prompts are explicit: PLAN, DESIGN, IMPLEMENT, and REVIEW.
- **Deterministic tests.** The runner executes the test commands itself, with no model call (`--test-cmd`, repeatable, or `MODEL_EFFORT_ROUTER_TEST_CMD`). Every code-change route needs at least one; without one the launcher exits 2 before any model stage, including `trivial_edit`. A green non-fast run moves to review; a failure sends only the failing command and a truncated log tail (80 lines / 6000 chars) to the cheap implementer. Interactive execution is limited to read-only routes and gated `trivial_edit` routes; the latter runs its deterministic check after the terminal session returns. Test commands come from the caller, not from plan text: a plan cannot make the launcher run shell commands the model wrote.
- **Review stage.** Every non-fast code-change route gets the merged review after a green test run, from the platform's `review` row at `max(level, WORKFLOW_MIN_LEVEL)` and the risk tier's effort (High / XHigh / Max); the implementer keeps its matrix profile. Only `trivial_edit` skips plan and review after meeting its deterministic-check gate. The reviewer's last line must be `VERDICT: PASS` or `VERDICT: FAIL` (only the final line counts, so an echoed prompt cannot force a pass); a missing verdict stops the run (exit 11) instead of passing. It receives the request, the plan, the test results, and the diff (capped), never the session.
- **Fail loop caps.** A failed test is fixed by the implementer up to 2 times per cycle; a review FAIL is fixed once. The next failure re-plans once with the planning model (the route's planner, or the reviewing judge for a single-stage route) and re-runs the implementer on the new plan, after which the counters reset (so the test-fix limit is per cycle). A `trivial_edit` has no review or re-plan: after the test-fix budget the run stops. Still failing after the re-plan budget: the run stops (exit 10; a stage that fails to start is 12, a missing plan file 13, any other stage failure passes its own exit code through). Route-file limits may only lower these caps, and every stage and test command has a timeout (1 hour / 30 minutes). An implementer whose last line is an `ESCALATE:` evidence line skips the fix budget and goes straight to the re-plan.
- **Stage permissions (Claude Code).** Non-interactive Claude stages get permission flags by role: implement and fix run with `--permission-mode acceptEdits`; plan and re-plan run in `dontAsk` mode and may write only the plan file (`Edit(//<abs plan path>)`, with Bash, NotebookEdit and MCP servers denied); review runs in `dontAsk` with Edit, Write, NotebookEdit, Bash and MCP denied, so a reviewer cannot fix code even where project settings allow it (deny rules beat allow rules). The plan directory is resolved once when the route is built so the prompt, the edit rule and the route agree (macOS `/var` vs `/private/var`); a plan path with parentheses is refused. The prompt follows `--` so it is never read as a tool name. `--dangerously-skip-permissions` is never used. Codex and Antigravity keep their own sandboxing. Because Bash is not pre-approved for the implementer either, a Claude implementer cannot run shell checks itself; the launcher's test gate does.
- **Route-file argv grammar.** A route file's `command` argv is accepted only in the shapes this router generates, for every schema version, in both `router.py --route-file` and `pipeline.py` (violations exit 2). A v6 or v7 Claude command must equal the generated argv for its step's model, effort and role (permission flags included, so no duplicate or widened permission flags); routes older than v6 predate permission flags and may only add the old `--agent <name>`. Codex accepts `-m` plus `-c model_reasoning_effort|developer_instructions`; Antigravity `--model` plus `--prompt`. Model ids are restricted to a strict charset (Antigravity display names may contain spaces and parentheses). For a v6 or v7 route each step's instructions are rebuilt and compared too: the Codex `developer_instructions` value (exactly one, and its reasoning effort equal to the step's) or, for Claude Code and Antigravity, the instruction block at the front of the prompt plus the verification handoff at its end, including the Autobahn scope guard when a security flag is set; only the task text in between is free. Routes older than v6 were written with older instruction texts and are checked against the grammar only. The rebuild inputs (`effective_level`, `task_type`, `mode`, `risk_flags`) and each step's model and effort are self-declared: someone who can edit a route file can still choose a level, model, effort or drop the security flag, provided the file stays internally consistent (pinning them needs reclassification or a signature over the file; replay does not re-derive them from the matrix because a route made with a custom `--config` must still replay). The fix, re-plan and re-implement stages take their scope guard from `risk_flags`, never from the top-level `scope_guard` block. A step whose instructions cannot be rebuilt (agent profile files missing on this install) is refused as unverifiable rather than as tampered. Rewording any pinned instruction text changes the route contract, so `SCHEMA_VERSION` must be bumped with it. Schema v7 uses role-specific prompts: PLAN for the minimum implementation plan, DESIGN for architecture plans, IMPLEMENT for approved-scope changes, and REVIEW for verification against requirements and plan. Multi-stage routes may not carry interactive (TUI) steps.
- **Fail-closed checks.** A planner that wrote no plan file stops the run (exit 13). In a git work tree (diffed against the HEAD seen when the run started, so commits count), an implementer that changed nothing fails the review without spending a review call, so it is fixed or re-planned like any other review FAIL.
- **Logging.** The runner logs one line per phase to stderr (`phase=implement model=... effort=...`, `phase=review ... attempt=N`); raw commands appear only with `MODEL_EFFORT_ROUTER_VERBOSE=1` or `--verbose`. `MODEL_EFFORT_ROUTER_PRINT_ONLY` prints just the replayable plan/implement command chain.
- **Review policy.** Do not call Sol/Opus after each step. Batch steps 1..N, run the tests, then make one Sol/Opus call that merges verification and code review. Send it only the original requirement, the approved plan, the git diff, the test results, and the key code, never the whole session. Default effort is High; the elevated tier uses XHigh and the critical tier Max.
- **Review FAIL.** The reviewer does not fix the problem. Every fix currently uses the route's implementer, and the second failure re-plans (Fail loop caps above). Planned (not implemented): the reviewer would grade the fix (simple / understanding / complex / replan) so a simple fix goes to Luna medium / Haiku, an ordinary logic change to Terra / Sonnet, and a design problem to a re-plan.
- **Implementation escalation.** If the implementer finds something outside the plan it stops and returns evidence for a Sol/Opus re-plan instead of deciding structure itself. Valid evidence: scope expansion, architecture change, public API change, DB migration, security boundary change, or a plan that no longer matches the code structure. "It is hard" or "I am unsure" alone is not a valid reason.
- **Follow-ups reuse the stored route** (no re-routing). Re-classify only when the task type changes (for example INSPECT to MODIFY), the scope grows a lot, new risk evidence appears, or a fact shows the approved design cannot be implemented. Runtime: name a session (`--session KEY` or `MODEL_EFFORT_ROUTER_SESSION`) and `router.py` stores the classification (task type, level, tier, risk flags, facts) under `MODEL_EFFORT_ROUTER_STATE_DIR` (default `~/.cache/model-effort-router`). A later task in the same session reuses it and skips the classifier unless a deterministic blocker fires: workspace changed; stored route older than 4 hours (reuse does not extend it); the route was already reused 10 times; the stored route still had unresolved facts (`unresolved`); the caller pins a different `--task-type`; an earlier pipeline run re-planned or failed (only `pipeline.py` records this, so a run through `--format command` never invalidates a route); the task text shows a different operation (inspect vs modify, mixed, or no recognisable operation for a stored read-only route), wider scope, or risk evidence in a dimension the stored route does not already cover (security words need a security flag, migration/production words a `data_migration` flag or the critical tier, public API words a `public_api_change` flag; a tier alone never covers security words). Text that names no operation reuses a stored code-change route. The record file is private (0600, owner-checked, size-capped, atomic rename, never through a symlink); a malformed record reclassifies. Unknown never blocks, so the caller's session key is what stands for "same target": use one session per task thread. `--no-reuse` and explicit pins bypass the store; fallback and manual routes are never stored; a corrupt or tampered record reclassifies. A reused route keeps its stored risk flags, tier and scope guard, and route JSON carries `reuse: {session, reused, reason}`.
- **Token savings.** Limit Sol/Opus to judgement; delegate coding; merge verification and review into one high-tier call; never re-classify the same scope; do not resend large output (send requirement + plan + diff + test results + key code); re-classify on new evidence, not on mere uncertainty.

## Verification recommendations

Every JSON route includes a `verification` object with `recommended` and `skipped` lists:

| ID | Recommended when |
|---|---|
| `focused_tests` | The task type changes code (`implementation`, `local_refactoring`, or `architectural_refactoring`) |
| `plan_validation` | The route uses two stages |
| `contract_review` | The task is `design` or `review`, or `public_api_change` is active |
| `security_review` | A security, authentication, authorization, or payment flag is active |
| `migration_safety` | `data_migration` is active |
| `broad_regression` | The effective level is L5 |

# Model Effort Router Policy (v4)

## Overview

The Model Effort Router classifies coding tasks by difficulty and risk, routing them to a matching model and reasoning-effort profile. The v4 route schema uses a 7-level scale (`L1` through `L7`) with a dedicated `Critical Override`, one repository-aware reclassification when an L4+ deciding fact is unknown, and deterministic Python mapping.

## Classification Architecture

The classifier answers facts; code decides the level. There are no difficulty scores
and no self-reported confidence.

```text
User Request
     │
Classifier (Luna Med / Sonnet 5 Med / Gemini 3.8 Flash Med, or the in-session difficulty-assessor agent)
  -> task_type + 16 facts (yes / no / unknown, plus a security domain and blast radius) + evidence
     │
DIFFICULTY_RULES (scripts/router.py)
  ├─ Base L2 (L1 when mechanical_only = yes)
  ├─ Highest matching rule wins; Critical rule -> Critical Profile
  └─ A rule >= L4 matched only through "unknown" -> needs_context
     │
needs_context -> one repository-aware classifier (Terra Med / Sonnet 5 Med / Gemini 3.1 Pro High)
  whose reply is combined with the first answer (the first is kept if it fails)
     │
Risk floors (Security/Payment change or critical-domain trust boundary -> L6, critical security domain -> L5, security review -> L4, Migration/Public API -> L4) -> Matrix lookup (task_type × level)
```

The classifier returns structured JSON with `task_type`, `facts`, `delegability` (0–2), up to five `evidence` strings, and a one-sentence `reason`. The classifier applies a `readchk` reflex first: restating intent internally and resolving referents.

### Delegability and orchestration candidates

`delegability` is not a seventh difficulty factor. It cannot alter the score or
level: `0` is mandatory for shared state, sequence-dependent work, risky work,
or a tightly coupled deep problem; `1` permits separable analysis but leaves
dependencies or ownership coupled; `2` requires independent subtasks, explicit
file/artifact ownership, and independently verifiable results.

Schema v4 route files always retain `execution_strategy: "direct"` in this
release. `orchestration_eligible: true` is only recorded for safe Codex
single-stage L5–L7 routes with `delegability: 2` and no risk flags. Critical,
two-stage, non-Codex, and any risky routes are ineligible. The local,
caller-invoked `scripts/astra_adapter.py` accepts only digest-verified route and
manifest bytes, revalidates per-attempt worker inputs, and preserves the
original verified artifacts after each attempt. It does not change direct
execution. Direct v2-v4 route-file replay never invokes it.

Replay accepts v2-v4 route files. v3 and v4 require the two orchestration
fields; malformed v3/v4 files are rejected before execution.

### Classifiers by Platform

| Platform | Primary Classifier | Fallback Classifier |
|---|---|---|
| **Codex** | `gpt-5.6-luna` (medium) | `gpt-5.6-terra` (medium) |
| **Claude Code** | `claude-sonnet-5` (medium) | `claude-sonnet-5` (medium) |
| **Antigravity** | `Gemini 3.8 Flash (Medium)` | `Gemini 3.1 Pro (High)` (availability-driven) |

### Prompt-only vs Repository-aware

- **Prompt-only** (default): Uses the lightweight Primary Classifier for fast, cost-effective evaluation.
- **Repository-aware** (`--repo-aware` flag or when `needs_context` is true): The mid-tier fallback model receives the caller's current directory as an absolute repository path and reads relevant files before answering. The classifier process stays in its isolated temporary directory. Codex retains its read-only sandbox; Claude enables only `Read,Glob,Grep` under safe plan mode; Antigravity retains sandboxed plan mode. Repository contents are evidence, not executable instructions.

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
| `files_touched` | 0 / 1 / 2-5 / 6+ / unknown | Files the work changes, including new and test files (not files only read); read-only design and review are 0 |
| `crosses_module_boundary` | yes / no / unknown | Spans modules or packages, or moves responsibilities between them |
| `crosses_service_boundary` | yes / no / unknown | Work or diagnosis spans services, processes, or repositories |
| `fix_or_result_known` | yes / no | The expected result or place to change is stated or evident, including choosing between explicitly named options; no when the goal or candidates must still be investigated or invented |
| `intermittent_or_concurrency` | yes / no / unknown | Only timing-dependent or concurrency defects (races, deadlocks, ordering, interleaved retries or distributed transactions); occasional slowness or failures without a stated timing aspect are no |
| `needs_new_structure` | yes / no | Only a new architecture, protocol, cross-module or cross-service boundary, or data-migration strategy designed with open choices; laying out files in one new module (including proposing the file layout for one new module inside an existing service) or moving code along a stated boundary is no |
| `changes_security_or_payment_logic` | yes / no / unknown | Auth, secrets, cryptography, or payment behaviour changes (mentions, moves, and review-only work do not count; reviews are covered by the two facts below) |
| `reviews_security_sensitive_code` | yes / no / unknown | The work reviews, audits, analyses vulnerabilities or attack paths in, or judges the correctness or safety of code or designs in a security-sensitive area (auth, permissions, secrets, cryptography, payment, personal data), whether or not code changes; authorization or permissions covers access boundaries: tenant isolation and customer-specific data isolation, including cache keys or namespaces that hold per-customer or per-tenant data (a wrong key can expose one customer's data to another) |
| `security_domain` | none / auth / payment / secrets / crypto / permissions / pii / unknown | The most critical security-sensitive area whose behaviour the work changes or whose correctness it judges (payment > crypto > auth > permissions > pii > secrets); `permissions` covers the access boundaries above (tenant isolation and customer-specific data isolation, including cache keys or namespaces that hold per-customer or per-tenant data; caching per-customer invoices is not payment but is a permissions review); `none` for mentions, moves, renames, or docs |
| `changes_public_api_contract` | yes / no / unknown | Externally consumed API, CLI, schema, or response format changes; a new endpoint consumed only by your own frontend, without changing existing external consumers or a published schema, is no |
| `changes_persisted_data` | yes / no / unknown | Stored data, database schema, or data migration changes; no when the task lists the files to change and none of them is a migration, schema, or repository/data-access file |
| `irreversible_or_ledger_or_crypto` | yes / no / unknown | Irreversible production data, ledger correctness, or designing new cryptographic algorithms/protocols/key-management (implementing or reviewing signing, verification, hashing, or token rotation with existing libraries is no; a schema or data migration that can be rolled back is no, as are retries, compensating transactions, idempotent re-runs, and other recoverable fixes) |
| `changes_trust_boundary` | yes / no / unknown | Designs, changes, or decides where trust is established or delegated between components, services, tenants, or principals (service-to-service auth, token propagation, permission delegation, isolation), including whether to move it; reviewing existing boundary code or moving code within one trust zone is no |
| `blast_radius` | narrow / broad / unknown | broad: a wrong result affects many services, all users or tenants, production data at large, external API consumers, or money/credentials system-wide; narrow: one component, feature, or a recoverable subset |
| `silent_failure_material_harm` | yes / no / unknown | A mistake could go unnoticed (no error, alert, or failing test) while causing data loss or corruption, wrong money movement, security exposure, or cross-service inconsistency |

Payment, in `changes_security_or_payment_logic`, `reviews_security_sensitive_code`, and `security_domain`, is decided by monetary consequence, not by a module or file named billing or order: moving money; determining the amount charged (price, discount, or tax calculation); authorizing, capturing, cancelling, or refunding payments, including an order cancellation that decides a refund; ledger or settlement correctness; or creating or changing a monetary obligation. Not payment: an order list UI, billing address edits, displaying an invoice PDF, order status strings, order creation that charges nothing, or code that merely lives in a billing or order module. Caching or reading billing or order data is not payment unless the cached or read value decides the amount charged.

Authorization or permissions, in `changes_security_or_payment_logic`, `reviews_security_sensitive_code`, and `security_domain`, is decided by access control boundaries (user authentication, RBAC, ACL, privilege, tenant isolation, credentials, or customer data isolation). Two narrow carve-outs are NOT authorization, permissions, or security changes: cost/model-tier confirmations (approving an expensive model before it runs, e.g. this router's Fable/Astra approval gate and its `--approved` flag), and plain UX confirmations that do not decide whether an action is allowed. Everything else that decides whether an agent, tool, or command may run without the user's consent IS authorization/permissions: tool or command permission prompts, sandbox or allowlist rules for shell commands, production or deploy approval gates, and adding, removing, or bypassing any such gate.

### Difficulty Rules

The level is the highest matching rule over a base of L2 (L1 when `mechanical_only` is yes).

| Level | Rule (all conditions must hold) |
|---|---|
| **Critical** | `irreversible_or_ledger_or_crypto` = yes |
| **L7** | `needs_new_structure` = yes, `security_domain` = payment, crypto, auth, permissions, or pii, `changes_trust_boundary` = yes |
| **L7** | `needs_new_structure` = yes, `crosses_service_boundary` = yes, `fix_or_result_known` = no, `blast_radius` = broad |
| **L7** | `needs_new_structure` = yes, `crosses_service_boundary` = yes, `fix_or_result_known` = no, `silent_failure_material_harm` = yes |
| **L6** | `needs_new_structure` = yes, `crosses_service_boundary` = yes, `fix_or_result_known` = no |
| **L6** | `security_domain` = payment, crypto, auth, permissions, or pii, `changes_trust_boundary` = yes |
| **L6** | `changes_security_or_payment_logic` = yes |
| **L6** | `intermittent_or_concurrency` = yes, `crosses_service_boundary` = yes |
| **L5** | `changes_security_or_payment_logic` = unknown |
| **L5** | `irreversible_or_ledger_or_crypto` = unknown |
| **L5** | `security_domain` = payment, crypto, auth, permissions, or pii |
| **L5** | `needs_new_structure` = yes |
| **L5** | `intermittent_or_concurrency` = yes |
| **L5** | `fix_or_result_known` = no, `crosses_module_boundary` = yes |
| **L4** | `reviews_security_sensitive_code` = yes or unknown |
| **L4** | `security_domain` = unknown |
| **L4** | `crosses_module_boundary` = yes |
| **L4** | `crosses_service_boundary`, `changes_public_api_contract`, or `changes_persisted_data` = yes or unknown |
| **L4** | `files_touched` = 6+ |
| **L3** | `files_touched` = 2-5 or unknown |
| **L3** | `fix_or_result_known` = no |

Security floors follow the impact of a wrong judgement, not whether code is edited: a review-only task in a security-sensitive area (`reviews_security_sensitive_code` = yes) floors at L4 independent of `task_type`, and a critical `security_domain` (payment, crypto, auth, permissions, pii) floors at L5. `secrets` alone has no floor of its own; it reaches L4 through the review fact or L6 through the change fact. These are floors: they never lower a higher matching rule or the Critical override.

L6/L7 follow the impact of a wrong judgement; `task_type` and whether code changes never lower a level. A critical `security_domain` whose trust boundary changes floors at L6. `needs_new_structure` is a design-difficulty signal, not an L7 signal by itself: a cross-service open design is L6, and reaches L7 only with a broad `blast_radius` or `silent_failure_material_harm` = yes, or when new structure is designed across a critical-domain trust boundary.

Unknown policy: an unknown security/payment change fact or an unknown irreversible/ledger/crypto fact routes at the L5 floor (never the Critical override, which fires only on an explicit yes); an unknown review fact or security domain takes at most the L4 floor (an unknown-driven L5 floor over-routed in evaluation); other unknown deciding facts take their rule. `intermittent_or_concurrency` = unknown is a needs_context-only signal: it triggers one repository-aware reclassification without raising the level floor by itself. The same holds for `changes_trust_boundary`, `blast_radius`, and `silent_failure_material_harm` = unknown; unknown never matches their L6/L7 conditions. `crosses_module_boundary` = unknown is likewise needs_context-only (an unknown module boundary over-routed single-module tasks to L4); only an explicit yes takes the L4 module-boundary rule, while `crosses_service_boundary` = unknown keeps its L4 rule. In contrast to the module boundary, a service boundary that stays unknown after the reclassification keeps the L4 floor (never L5): a multi-service task must not fall to L3 only because the boundary could not be settled, while an escalated yes takes the normal L4 rule and an escalated no routes on the other facts alone. A rule at L4 or above that matched only through `unknown` sets `needs_context` and triggers one repository-aware reclassification. The escalated classifier read the repository, but only some safety facts may be lowered by it. A sticky primary affirmative — security/payment change, persisted-data, public-API, irreversible/ledger/crypto, trust-boundary change, or silent material harm — is OR-aggregated and can never be lowered by the escalated reply, because missing one of these under-routes a real irreversible or security change (`irreversible_or_ledger_or_crypto` = yes from the primary always keeps the Critical override, whatever escalated answers). A correctable primary affirmative — a critical `security_domain`, `reviews_security_sensitive_code`, or a broad `blast_radius` — is where a keyword-driven primary classifier produces most of its false positives on ordinary review-scope tasks, so the escalated reply may correct it once it gives an explicit, non-`unknown` answer: `reviews_security_sensitive_code` and `blast_radius` keep the primary's affirmative unless escalated explicitly answers `no` or `narrow`; `security_domain` keeps the primary's critical domain while escalated stays `unknown`, takes escalated's explicit `none`, and otherwise keeps whichever of the two named domains is more critical by priority (payment > crypto > auth > permissions > pii > secrets). An unrelated unknown elsewhere in the escalated reply still cannot lower a floor these facts do settle. A failed escalation (fallback) never replaces the primary, whose own facts and floors stand as classified.

### Risk Flags and Hard Floors

Risk flags are derived from facts: `changes_security_or_payment_logic` = yes sets `security_sensitive`, `changes_persisted_data` = yes sets `data_migration`, and `changes_public_api_contract` = yes sets `public_api_change`. Manual and pinned classifications may carry any of:

```text
security_sensitive   authentication      authorization
payment              data_migration      public_api_change
```

- Any of `security_sensitive`, `authentication`, `authorization`, or `payment` (when involving actual code/behavior changes) forces a hard floor of **L6** and activates an Autobahn scope guard instruction. Non-security changes mentioning security terms (such as typo fixes or documentation edits) do not activate these flags and remain at their natural score (e.g. L1).
- An active `data_migration` or `public_api_change` forces a floor of **L4**. Floors do not stack: the risk factor already scores these risks.
- Review-only security work sets no risk flag (the L6 change floor and the Autobahn scope guard belong to behaviour changes); its L4/L5 floors come from `DIFFICULTY_RULES` alone.
- **Critical Override**: Irreversible data migration, mass production data deletion, financial ledger correctness, designing new cryptographic algorithms/protocols/key-management, or explicit `--critical` argument overrides the level directly to the **Critical Profile** (`GPT-6 Astra Max` / `Claude Opus Max`). Fires only on an explicit yes; an unknown never triggers it.

## Default Execution Model Map

### Codex Matrix

| task_type | L1 | L2 | L3 | L4 | L5 | L6 | L7 | Critical |
|---|---|---|---|---|---|---|---|---|
| implementation | luna low | luna med | terra med | terra high | sol high | sol xhigh | astra xhigh | astra max |
| design | luna med | sol low | sol med | sol high | sol high | sol xhigh | astra xhigh | astra max |
| review | luna med | sol low | sol med | sol high | sol high | sol xhigh | astra xhigh | astra max |
| local_refactoring | luna low | luna med | terra med | terra high | sol high | sol xhigh | astra xhigh | astra max |
| architectural_refactoring | luna med | sol med | sol high → terra med | sol xhigh → terra high | sol xhigh → terra high | sol xhigh → sol xhigh | astra xhigh → sol xhigh | astra max |

### Claude Code Matrix

Claude Code uses an ordered candidate list for L5~L7 and Critical: **Fable 5.1 primary with availability fallback to Opus 5** (`claude-fable-5-1` → `claude-opus-5`). When available models are provided, Fable is chosen if entitled/available, otherwise falling back to Opus 5.

| task_type | L1 | L2 | L3 | L4 | L5 | L6 | L7 | Critical |
|---|---|---|---|---|---|---|---|---|
| implementation | haiku | haiku | sonnet med | sonnet high | fable med (opus med) | fable high (opus high) | fable xhigh (opus xhigh) | fable max (opus max) |
| design | haiku | opus low | opus med | opus high | fable high (opus high) | fable xhigh (opus xhigh) | fable xhigh (opus xhigh) | fable max (opus max) |
| review | haiku | opus low | opus med | opus high | fable high (opus high) | fable xhigh (opus xhigh) | fable xhigh (opus xhigh) | fable max (opus max) |
| local_refactoring | haiku | haiku | sonnet med | sonnet high | fable med (opus med) | fable high (opus high) | fable xhigh (opus xhigh) | fable max (opus max) |
| architectural_refactoring | haiku | opus med | fable high → sonnet med | fable xhigh → sonnet high | fable xhigh → sonnet high | fable xhigh → fable high | fable max → fable xhigh | fable max (opus max) |

### Antigravity Matrix

Antigravity uses `Gemini 3.8 Flash (High)` as its minimum execution floor:

| task_type | L1 | L2 | L3 | L4 | L5 | L6 | L7 | Critical |
|---|---|---|---|---|---|---|---|---|
| implementation | Flash High | Flash High | Flash High | Sonnet Thinking | Pro High | Opus/Fable Thinking | Opus/Fable Thinking | Opus/Fable Thinking |
| design | Flash High | Flash High | Pro High | Pro High | Pro High | Opus/Fable Thinking | Opus/Fable Thinking | Opus/Fable Thinking |
| review | Flash High | Flash High | Pro High | Pro High | Pro High | Opus/Fable Thinking | Opus/Fable Thinking | Opus/Fable Thinking |
| local_refactoring | Flash High | Flash High | Flash High | Sonnet Thinking | Pro High | Opus/Fable Thinking | Opus/Fable Thinking | Opus/Fable Thinking |
| architectural_refactoring | Flash High | Flash High | Pro High → Flash High | Pro High → Sonnet Thinking | Pro High → Sonnet Thinking | Opus/Fable Thinking → Opus/Fable Thinking | Opus/Fable Thinking → Opus/Fable Thinking | Opus/Fable Thinking |

`A → B` marks two-stage architectural refactoring: stage A plans, stage B executes.
- `Opus/Fable Thinking` on Antigravity resolves availability-driven: `Claude Fable .*(Thinking)` → `Claude Opus 5 .*(Thinking)` → `Claude Opus 4.6 (Thinking)` (fallback).
- `Pro High` on Antigravity resolves availability-driven: preferred `Gemini 3.1 Pro (High)` → `Gemini .* Pro (High)` → `Claude Sonnet .* (Thinking)`.
- `sonnet` on Claude Code refers to `claude-sonnet-5` (with medium effort at L3 and high effort at L4); `haiku` refers to `claude-haiku-4-5` without effort parameter; `fable` refers to `claude-fable-5-1` and `opus` refers to `claude-opus-5`.


## Verification recommendations

Every JSON route includes a `verification` object with `recommended` and `skipped` lists:

| ID | Recommended when |
|---|---|
| `focused_tests` | The task type changes code (`implementation`, `local_refactoring`, or `architectural_refactoring`) |
| `plan_validation` | The route uses two stages |
| `contract_review` | The task is `design` or `review`, or `public_api_change` is active |
| `security_review` | A security, authentication, authorization, or payment flag is active |
| `migration_safety` | `data_migration` is active |
| `broad_regression` | The effective level is L5, L6, L7, or Critical |

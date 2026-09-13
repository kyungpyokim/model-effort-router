# Model Effort Router Policy (v2.1)

## Overview

The Model Effort Router classifies coding tasks by difficulty and risk, routing them to a matching model and reasoning-effort profile. The v2 policy uses a 7-level scale (`L1` through `L7`) with a dedicated `Critical Override`, cascading classification (lightweight primary classifier with confidence-gated fallback to mid-tier), and deterministic Python mapping.

## Classification Architecture

The classifier answers facts; code decides the level. There are no difficulty scores
and no self-reported confidence.

```text
User Request
     │
Classifier (Luna Med / Haiku 4.5 / Gemini 3.8 Flash Med, or the in-session difficulty-assessor agent)
  -> task_type + 11 facts (yes / no / unknown) + evidence
     │
DIFFICULTY_RULES (scripts/router.py)
  ├─ Base L2 (L1 when mechanical_only = yes)
  ├─ Highest matching rule wins; Critical rule -> Critical Profile
  └─ A rule >= L4 matched only through "unknown" -> needs_context
     │
needs_context -> one repository-aware classifier (Terra Med / Sonnet 5 Med / Gemini 3.1 Pro High)
  whose facts replace the first answer (the first is kept if it fails)
     │
Risk floors (Security/Payment -> L6, Migration/Public API -> L4) -> Matrix lookup (task_type × level)
```

The classifier returns structured JSON with `task_type`, `facts`, `delegability` (0–2), up to five `evidence` strings, and a one-sentence `reason`. The classifier applies a `readchk` reflex first: restating intent internally and resolving referents.

### Delegability and orchestration candidates

`delegability` is not a seventh difficulty factor. It cannot alter the score or
level: `0` is mandatory for shared state, sequence-dependent work, risky work,
or a tightly coupled deep problem; `1` permits separable analysis but leaves
dependencies or ownership coupled; `2` requires independent subtasks, explicit
file/artifact ownership, and independently verifiable results.

Schema v3 route files always retain `execution_strategy: "direct"` in this
release. `orchestration_eligible: true` is only recorded for safe Codex
single-stage L5–L7 routes with `delegability: 2` and no risk flags. Critical,
two-stage, non-Codex, and any risky routes are ineligible. The local,
caller-invoked `scripts/astra_adapter.py` accepts only digest-verified route and
manifest bytes, revalidates per-attempt worker inputs, and preserves the
original verified artifacts after each attempt. It does not change direct
execution. Direct v2 and v3 route-file replay never invokes it.

Replay accepts existing v2 route files unchanged. Only v3 requires the two
orchestration fields; malformed v3 files are rejected before execution.

### Classifiers by Platform

| Platform | Primary Classifier | Fallback Classifier |
|---|---|---|
| **Codex** | `gpt-5.6-luna` (medium) | `gpt-5.6-terra` (medium) |
| **Claude Code** | `claude-haiku-4-5` (no effort) | `claude-sonnet-5` (medium) |
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
| `files_touched` | 1 / 2-5 / 6+ / unknown | Files the work edits or must examine closely |
| `crosses_module_boundary` | yes / no / unknown | Spans modules or packages, or moves responsibilities between them |
| `crosses_service_boundary` | yes / no / unknown | Work or diagnosis spans services, processes, or repositories |
| `fix_or_result_known` | yes / no | The expected result or place to change is stated or evident |
| `intermittent_or_concurrency` | yes / no | Intermittent, timing-dependent, or concurrent behaviour |
| `needs_new_structure` | yes / no | New architecture, protocol, module boundary, or migration strategy |
| `changes_security_or_payment_logic` | yes / no / unknown | Auth, secrets, cryptography, or payment behaviour changes (mentions or moves do not count) |
| `changes_public_api_contract` | yes / no / unknown | Externally consumed API, CLI, schema, or response format changes |
| `changes_persisted_data` | yes / no / unknown | Stored data, database schema, or data migration changes |
| `irreversible_or_ledger_or_crypto` | yes / no | Irreversible production data, ledger correctness, or cryptographic design |

### Difficulty Rules

The level is the highest matching rule over a base of L2 (L1 when `mechanical_only` is yes).

| Level | Rule (all conditions must hold) |
|---|---|
| **Critical** | `irreversible_or_ledger_or_crypto` = yes |
| **L7** | `needs_new_structure` = yes, `crosses_service_boundary` = yes, `fix_or_result_known` = no |
| **L6** | `changes_security_or_payment_logic` = yes |
| **L6** | `intermittent_or_concurrency` = yes, `crosses_service_boundary` = yes |
| **L5** | `changes_security_or_payment_logic` = unknown |
| **L5** | `needs_new_structure` = yes |
| **L5** | `intermittent_or_concurrency` = yes |
| **L5** | `fix_or_result_known` = no, `crosses_module_boundary` = yes |
| **L4** | `crosses_module_boundary`, `crosses_service_boundary`, `changes_public_api_contract`, or `changes_persisted_data` = yes or unknown |
| **L4** | `files_touched` = 6+ |
| **L3** | `files_touched` = 2-5 or unknown |
| **L3** | `fix_or_result_known` = no |

Unknown policy: an unknown security/payment fact routes one level below the security floor (L5); other unknown deciding facts take their rule. A rule at L4 or above that matched only through `unknown` sets `needs_context` and triggers one repository-aware reclassification.

### Risk Flags and Hard Floors

Risk flags are derived from facts: `changes_security_or_payment_logic` = yes sets `security_sensitive`, `changes_persisted_data` = yes sets `data_migration`, and `changes_public_api_contract` = yes sets `public_api_change`. Manual and pinned classifications may carry any of:

```text
security_sensitive   authentication      authorization
payment              data_migration      public_api_change
```

- Any of `security_sensitive`, `authentication`, `authorization`, or `payment` (when involving actual code/behavior changes) forces a hard floor of **L6** and activates an Autobahn scope guard instruction. Non-security changes mentioning security terms (such as typo fixes or documentation edits) do not activate these flags and remain at their natural score (e.g. L1).
- An active `data_migration` or `public_api_change` forces a floor of **L4**. Floors do not stack: the risk factor already scores these risks.
- **Critical Override**: Irreversible data migration, mass production data deletion, financial ledger correctness, cryptographic design, or explicit `--critical` argument overrides the level directly to the **Critical Profile** (`GPT-6 Astra Max` / `Claude Opus Max`).

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

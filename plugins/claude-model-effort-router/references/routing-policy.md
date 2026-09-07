# Model Effort Router Policy (v2.0)

## Overview

The Model Effort Router classifies coding tasks by difficulty and risk, routing them to a matching model and reasoning-effort profile. The v2 policy uses a 7-level scale (`L1` through `L7`) with a dedicated `Critical Override`, cascading classification (lightweight primary classifier with confidence-gated fallback to mid-tier), and deterministic Python mapping.

## Classification Architecture

Classification evaluates six factors (each scored 0–2, total 0–12):

```text
User Request
     │
Hard Floor Rules (Security, Auth, Payment, Migration)
     │
Cascading Classifier
  Primary (Luna Med / Haiku 4.5 / Gemini 3.8 Flash Med)
     │
Confidence Check
  ├─ >= 0.80 ──────> Adopt score directly
  ├─ 0.60 - 0.79 ──> Conservative bump (+1 level)
  └─ < 0.60 ───────> Fallback Classifier (Terra Med / Sonnet 5 Med / Gemini 3.1 Pro High)
     │
Python Deterministic Mapping
  ├─ Score -> L1~L7 Level
  ├─ Hard Floor Check (Security/Auth/Payment -> L6)
  ├─ Critical Override (Catastrophic/Irreversible -> Critical Profile)
  └─ Matrix lookup (task_type × level)
```

The classifier returns structured JSON with `task_type`, six factor scores, `level`, six `risk_flags`, `confidence`, `context_required` (boolean), and a one-sentence `reason`. The classifier applies a `readchk` reflex before scoring: restating intent internally and resolving referents.

### Classifiers by Platform

| Platform | Primary Classifier | Fallback Classifier |
|---|---|---|
| **Codex** | `gpt-5.6-luna` (medium) | `gpt-5.6-terra` (medium) |
| **Claude Code** | `claude-haiku-4-5` (no effort) | `claude-sonnet-5` (medium) |
| **Antigravity** | `Gemini 3.8 Flash (Medium)` | `Gemini 3.1 Pro (High)` (availability-driven) |

### Prompt-only vs Repository-aware

- **Prompt-only** (default): Uses the lightweight Primary Classifier for fast, cost-effective evaluation.
- **Repository-aware** (`--repo-aware` flag or when `context_required: true`): When codebase search across dozens of files is required to judge difficulty, the classifier escalates directly to the mid-tier fallback model.

### Task types

| `task_type` | Meaning |
|---|---|
| `implementation` | Build or change code directly: features, APIs, UI work, bug fixes, tests |
| `design` | Decide structure or direction without editing code: architecture, API or data-model design, technology choice, planning |
| `review` | Analyse existing code or plans to find problems: code, PR, security, performance, design review |
| `local_refactoring` | Clean internals while preserving behaviour and module boundaries: extract functions, renames, deduplication, simplification in one module |
| `architectural_refactoring` | Change module boundaries or system structure AND carry out the resulting edits: module splits, dependency inversion, state-management changes, data-layer redesign |

Mixed tasks classify by their primary purpose. Design with sample code is `design`; implementation that needs small judgement calls is `implementation`; structural change followed by real multi-file edits is `architectural_refactoring`.

### Factor scoring

| Factor | 0 | 1 | 2 |
|---|---|---|---|
| **Scope** | One local edit | One component or module | Multiple modules, services, or repositories |
| **Ambiguity** | Explicit expected result | Some interpretation required | Requirements are unclear, conflicting, or exploratory |
| **Diagnosis** | No investigation | Known-area debugging | Root cause unknown, intermittent, or cross-system |
| **Design** | Follow an existing pattern | Choose among existing patterns | New architecture, protocol, or migration strategy |
| **Risk** | Easily reversible | User-facing regression possible | Security, money, production data, or availability risk |
| **Verification** | Visual or local check | Unit or focused integration tests | End-to-end, migration, load, or broad regression validation |

### Score to Level Mapping

| Total Score | Level | Name | Typical Tasks |
|---:|---|---|---|
| **0 - 1** | **L1** | trivial | Renames, formatting, typos, imports, single-line assertion fix |
| **2 - 3** | **L2** | simple | Small function, DTO/schema addition, standard unit test, 2-3 files |
| **4 - 5** | **L3** | standard | CRUD, API endpoint, React component, DB query, normal bug fix |
| **6 - 7** | **L4** | complex | Multi-module logic, async pipelines, state management, mid-scale refactor |
| **8 - 9** | **L5** | advanced | Root cause investigation, performance analysis, N+1 optimization, trade-offs |
| **10 - 11** | **L6** | expert | Concurrency/race conditions, distributed systems, auth/security-critical |
| **12** | **L7** | frontier | Whole-system re-architecture, massive scope, exploratory cross-system E2E |

### Risk Flags and Hard Floors

The classifier reports boolean flags:

```text
security_sensitive   authentication      authorization
payment              data_migration      public_api_change
```

- Any of `security_sensitive`, `authentication`, `authorization`, or `payment` (when involving actual code/behavior changes) forces a hard floor of **L6** and activates an Autobahn scope guard instruction. Non-security changes mentioning security terms (such as typo fixes or documentation edits) do not activate these flags and remain at their natural score (e.g. L1).
- Each active `data_migration` or `public_api_change` escalates one further level (up to L7).
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

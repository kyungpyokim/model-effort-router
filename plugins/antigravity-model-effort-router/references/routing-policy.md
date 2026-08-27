# Model Effort Router Policy

## Classification

Classify each coding task with its selected platform's native CLI: Codex uses
`gpt-5.6-terra` / low, Claude Code uses `claude-sonnet-5` / low, and
Antigravity uses `gemini-3.6-flash-low`. Return structured JSON with a
`task_type`, all six factor scores, a level, six risk flags, a confidence, and
a one-sentence reason. The classifier applies a `readchk` reflex before scoring:
restating intent internally and resolving referents. If genuine conflicting interpretations
exist, ambiguity is scored as 2 and the surviving fork is stated in reason (which
may escalate borderline tasks by one level through the factor score).
The router validates the exact schema before using it; it never infers risk from
keywords or language rules.

### Task types

| `task_type` | Meaning |
|---|---|
| `implementation` | Build or change code directly: features, APIs, UI work, bug fixes, tests |
| `design` | Decide structure or direction without editing code: architecture, API or data-model design, technology choice, planning |
| `review` | Analyse existing code or plans to find problems: code, PR, security, performance, design review |
| `local_refactoring` | Clean internals while preserving behaviour and module boundaries: extract functions, renames, deduplication, simplification in one module |
| `architectural_refactoring` | Change module boundaries or system structure AND carry out the resulting edits: module splits, dependency inversion, state-management changes, data-layer redesign |

Mixed tasks classify by their primary purpose. Design with sample code is
`design`; implementation that needs small judgement calls is
`implementation`; structural change followed by real multi-file edits is
`architectural_refactoring`.

### Factor scoring

| Factor | 0 | 1 | 2 |
|---|---|---|---|
| Scope | One local edit | One component or module | Multiple modules, services, or repositories |
| Ambiguity | Explicit expected result | Some interpretation required | Requirements are unclear, conflicting, or exploratory |
| Diagnosis | No investigation | Known-area debugging | Root cause unknown, intermittent, or cross-system |
| Design | Follow an existing pattern | Choose among existing patterns | New architecture, protocol, or migration strategy |
| Risk | Easily reversible | User-facing regression possible | Security, money, production data, or availability risk |
| Verification | Visual or local check | Unit or focused integration tests | End-to-end, migration, load, or broad regression validation |

| Total | Level |
|---:|---|
| 0-2 | L1 |
| 3-5 | L2 |
| 6-8 | L3 |
| 9-10 | L4 |
| 11-12 | L5 |

Levels weigh complexity, scope, and risk above raw code volume.

L1 is one function or file with explicit requirements. L2 touches a few files
following existing patterns. L3 is feature-sized implementation with tests and
bounded design judgement. L4 crosses modules or services and includes complex
debugging or migration. L5 is open-ended, system-wide, or high failure cost.

### Risk flags

The classifier reports exactly these boolean flags; the router — not the
prompt — applies policy:

```text
security_sensitive   authentication      authorization
payment              data_migration      public_api_change
```

Any of `security_sensitive`, `authentication`, `authorization`, or `payment`
forces a hard floor of L4 and activates an Autobahn scope guard instruction,
isolating sensitive boundaries and requiring safe scopes to be verified first.
Each active `data_migration` or `public_api_change` escalates one further level.
The result never exceeds L5.

## Overrides and failures

- `--task-type auto` (default) classifies the type. An explicit value replaces
  only the classified type; level and risk flags are still judged. Invalid
  values fail immediately instead of falling back.
- `--level` is a minimum, never a cap. With both an explicit type and an
  explicit `--level L5`, the preflight is skipped entirely because both axes
  are pinned. An explicit `--level L5` alone still classifies so the task-type
  axis picks the right profile row.
- Explicit factors override only their corresponding classifier scores. The
  router recomputes the score minimum but never lowers the semantic level.
- On timeout, process failure, or invalid structured output, select the safe
  fallback: `implementation` / `L3` / `luna xhigh`. The fallback is reported
  on stderr.

## Execution rules

1. State the selected task_type, level, model, and effort before substantial work.
2. Route once; do not recursively invoke the router from a routed agent.
3. Re-evaluate only if scope or risk materially changes.
4. Keep platform mappings editable in `config/model-map.json`.

## Verification recommendations

Every JSON route includes a `verification` object with `recommended` and
`skipped` lists. Each item has a stable `id` and a human-readable `reason`.
It is guidance only: the router does not choose or execute repository-specific
commands, and a skipped item does not prohibit an operator from running it.

The checks are evaluated in this order:

| ID | Recommended when |
|---|---|
| `focused_tests` | The task type changes code (`implementation`, `local_refactoring`, or `architectural_refactoring`) |
| `plan_validation` | The route uses two stages |
| `contract_review` | The task is `design` or `review`, or `public_api_change` is active |
| `security_review` | A security, authentication, authorization, or payment flag is active |
| `migration_safety` | `data_migration` is active |
| `broad_regression` | The effective level is L4 or L5 |

Route-file replay ignores `verification` when building the execution command;
it reuses only the stored platform execution steps and never reclassifies.

## Two-stage architectural refactoring

`architectural_refactoring` at L3 or above runs as two chained stages:

1. **Plan** — `sol` analyses the repository and writes a structured plan JSON
   to a temporary run directory (`/tmp/codex-route-<run-id>/plan.json`). It
   modifies no other file. The planner applies `re0` and `debloat` principles:
   producing a clean v0 specification without speculative boilerplate or process
   noise, cutting words while keeping load-bearing rules and invariant mechanisms.
2. **Execute** — the executor model reads the original request plus the plan
   file, verifies the plan against the current repository state, applies the
   changes, and runs the plan's validation commands. The executor applies `re0`
   hygiene, leaving touched artifacts cleaner than found and removing scaffolding residue.

The execute stage runs only if the plan stage succeeds. On success the run
directory is removed; on any failure it is preserved for inspection.
`--keep-plan` preserves it even on success.

Architectural refactoring that only needs a design document reclassifies as
`design`; the two-stage path therefore always includes execution. L1-L2 rows
stay single-stage because such small scopes should have been L3+ if they truly
required a separate executor.

## Default model map

Role mapping per platform — luna = light execution, sol = judgement and
analysis, terra = wide long execution:

| Role | Codex | Claude Code | Antigravity |
|---|---|---|---|
| luna | `gpt-5.6-luna` | `haiku` | Gemini Flash (Low/Medium/High) |
| terra | `gpt-5.6-terra` | `sonnet` | Claude Sonnet (Thinking) |
| sol | `gpt-5.6-sol` | `opus` | Gemini Pro (High) / Claude Opus (Thinking) |

### Codex (`task_type × level` matrix)

| task_type | L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|
| implementation | luna medium | luna high | luna xhigh | terra xhigh | terra max |
| design | sol low | sol medium | sol high | sol xhigh | sol max |
| review | sol low | sol medium | sol high | sol xhigh | sol max |
| local_refactoring | luna medium | luna high | luna xhigh | terra xhigh | terra max |
| architectural_refactoring | sol medium | sol high | sol high → luna xhigh | sol xhigh → terra xhigh | sol max → terra max |

### Claude Code (`task_type × level` matrix)

| task_type | L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|
| implementation | haiku medium | haiku high | haiku xhigh | sonnet xhigh | sonnet max |
| design | opus low | opus medium | opus high | opus xhigh | opus max |
| review | opus low | opus medium | opus high | opus xhigh | opus max |
| local_refactoring | haiku medium | haiku high | haiku xhigh | sonnet xhigh | sonnet max |
| architectural_refactoring | opus medium | opus high | opus high → haiku xhigh | opus xhigh → sonnet xhigh | opus max → sonnet max |

### Antigravity (`task_type × level` matrix, effort embedded in model names)

Antigravity exposes effort in model display names; each cell holds ordered
regular expressions matched against `agy models` output with a configured
fallback, so account-local naming never breaks routing.

| task_type | L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|
| implementation | Flash Low | Flash Medium | Flash High | Sonnet Thinking | Opus Thinking |
| design | Flash High | Pro High | Pro High | Pro High | Opus Thinking |
| review | Flash High | Pro High | Pro High | Pro High | Opus Thinking |
| local_refactoring | Flash Low | Flash Medium | Flash High | Sonnet Thinking | Opus Thinking |
| architectural_refactoring | Flash High | Pro High | Pro High → Flash High | Pro High → Sonnet Thinking | Opus Thinking → Opus Thinking |

`A → B` marks the two-stage path: A plans, B executes. Two-stage runs use the
same plan-file protocol on every platform; only the launch argv differs
(`codex exec`, `claude -p`, `agy --prompt`).

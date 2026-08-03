# Model Effort Router Policy

## Classification

Classify each coding task with the installed Codex CLI using fixed
`gpt-5.6-terra` and low reasoning effort. Return structured JSON with all six
factor scores, a level, and a short rationale. The router validates the exact
schema before using it; it never infers risk from keywords or language rules.

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

Apply at least L4 for authentication or authorization, public API
compatibility, production incidents, database migrations, payments,
security-sensitive code, or multi-service deployment. Apply L5 for
irreversible deletion, cryptographic design, compliance/legal or financial
correctness, broad live incidents, or material harm.

## Overrides and failures

- `--level` is a minimum, never a cap. L1-L4 still use Terra classification;
  `--level L5` skips it because no route can be higher.
- Explicit factors override only their corresponding Terra scores. The router
  recomputes the score minimum but never lowers Terra's semantic level.
- On timeout, process failure, or invalid structured output, select safe L3.

## Execution rules

1. State the selected level, model, and effort before substantial work.
2. Route once; do not recursively invoke the router from a routed agent.
3. Re-evaluate only if scope or risk materially changes.
4. Keep platform mappings editable in `config/model-map.json`.

## Default model map

### Codex

| Level | Model | Effort |
|---|---|---|
| L1 | gpt-5.6-luna | low |
| L2 | gpt-5.6-terra | medium |
| L3 | gpt-5.6-terra | high |
| L4 | gpt-5.6-sol | xhigh |
| L5 | gpt-5.6-sol | max |

### Claude Code

| Level | Model | Effort |
|---|---|---|
| L1 | sonnet | low |
| L2 | sonnet | medium |
| L3 | sonnet | high |
| L4 | opus | xhigh |
| L5 | opus | max |

### Antigravity

Antigravity exposes effort in model display names. Match the first available
model through the ordered regular expressions in `config/model-map.json`.

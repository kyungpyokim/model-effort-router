# Model Effort Router Policy

## Goal

Classify a coding task by difficulty, then select one model-and-effort profile as a single unit. Do not choose the model and effort independently.

## Difficulty factors

Score each factor from 0 to 2.

| Factor | 0 | 1 | 2 |
|---|---|---|---|
| Scope | One local edit | One component or module | Multiple modules, services, or repositories |
| Ambiguity | Explicit expected result | Some interpretation required | Requirements are unclear, conflicting, or exploratory |
| Diagnosis | No investigation | Known-area debugging | Root cause unknown, intermittent, or cross-system |
| Design | Follow an existing pattern | Choose among existing patterns | Define a new architecture, protocol, or migration strategy |
| Risk | Easily reversible | User-facing regression possible | Security, money, production data, or availability risk |
| Verification | Visual or local check | Unit or focused integration tests | End-to-end, migration, load, or broad regression validation |

## Score mapping

| Total | Level | Name |
|---:|---|---|
| 0-2 | L1 | Simple |
| 3-5 | L2 | Standard |
| 6-8 | L3 | Complex |
| 9-10 | L4 | Advanced |
| 11-12 | L5 | Critical |

## Hard floors

Raise the result after scoring when any rule applies.

- At least L4: authentication or authorization changes, public API compatibility changes, production incidents, database migrations, payment flows, security-sensitive code, multi-service deployment changes.
- L5: irreversible data deletion, cryptographic design, compliance or legal correctness, financial ledger correctness, live incident remediation with broad blast radius, or a change where silent failure can cause material harm.
- Never lower an explicit user-requested level. An explicit level may raise the automatic result.

## Common execution rules

1. State the selected level, model, and effort in one compact line before substantial work.
2. Route once. Do not recursively invoke the router from a routed agent.
3. Re-evaluate only when the task scope changes materially or new evidence raises the risk.
4. Prefer the lowest level that safely covers the task, but apply hard floors conservatively.
5. If a configured model is unavailable, use the nearest available fallback in the same or higher capability tier and report the fallback.
6. Keep model mappings editable in `config/model-map.json`; do not hard-code account-specific model availability into the policy.

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

Antigravity exposes effort as part of the model display name. Match the first available model using the ordered regular expressions in `config/model-map.json`.

| Level | Preferred class |
|---|---|
| L1 | Gemini Flash Low |
| L2 | Gemini Flash Medium |
| L3 | Gemini Flash High |
| L4 | Gemini Pro High, then Claude Sonnet Thinking |
| L5 | Claude Opus Thinking, then the strongest available Pro/Thinking model |

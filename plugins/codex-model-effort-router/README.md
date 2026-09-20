# Codex Model Effort Router

## What it does

The skill classifies each task by `task_type` (implementation, design, review,
local_refactoring, architectural_refactoring) and difficulty (L1-L5) plus a risk tier (`standard`, `elevated`, `critical`), then
routes it through the v5 `task_type × level` matrix in `config/model-map.json`:

| task type | L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|
| implementation / local_refactoring | luna low | luna med | terra med | terra high | sol high -> terra high |
| design / review | luna med | sol high | sol high | sol high | sol high |
| architectural_refactoring | luna med | sol high | sol high -> terra med | sol xhigh -> terra high | sol xhigh -> terra high |

`A -> B` is the success-dependent planner-to-implementer chain (`architectural_refactoring`
L3+, and `implementation` / `local_refactoring` at L5). The `elevated` and `critical`
risk tiers imply L5 and raise only the planning/judging stage (the planner of a
two-stage route, otherwise the single stage) to `xhigh` / `max`. Read-only
design and review use `files_touched: 0`; files only read for context do not count.

Security-related risk flags (security_sensitive, authentication,
authorization, payment) force the elevated tier (L5) before the matrix lookup. Review-only
security work floors through facts instead: `reviews_security_sensitive_code`
at L4 and a critical `security_domain` (payment, crypto, auth, permissions, pii)
at L5, whatever the task type. A critical domain whose trust boundary changes is
elevated; `irreversible_or_ledger_or_crypto` = yes or `--critical` is the critical
tier. Rules never drive difficulty on their own: the keyword "security" alone implies
no level, and `unknown` is missing information, not confirmed risk. `--level`
accepts `L1`-`L5` only.

## Execution roles and pipeline

Goal: **Sol thinks and verifies, Luna and Terra implement.** Sol designs,
verifies, and reviews; Luna/Terra implement, fix, and run tests; re-promote to Sol
when the implementation hits a new design problem. Classification stays on Luna.

- Reuse the stored route for follow-up questions in the same task. Re-classify only
  when the task type changes, scope grows a lot, new risk evidence appears, or a
  fact shows the approved design cannot be implemented.
- Classify each planned step again (tweak or tests -> Luna med, ordinary logic ->
  Terra); test execution (pytest, lint, typecheck, build) belongs to the cheap models.
- Do not call Sol after each step. After steps 1..N and the tests, make one Sol
  verification + code review call (High; elevated tier XHigh; critical tier Max),
  sent only the requirement, approved plan, git diff, test results, and key code.
- On review FAIL the reviewer does not fix it: re-classify the fix (simple -> Luna
  med, ordinary logic -> Terra, design problem -> Sol), then a final Sol review.
- An implementer that finds something outside the plan stops and returns evidence
  (scope expansion, architecture or public API change, DB migration, security
  boundary change, plan/code mismatch) for a Sol re-plan; "hard" or "unsure" alone
  is not evidence.

See `references/routing-policy.md` for the full rules.

## Test locally

From the bundle root, register the local marketplace and install the plugin:

```bash
codex plugin marketplace add /absolute/path/to/model-effort-router
codex plugin add model-effort@model-effort-router-bundle
```

The plugin manifest is `.codex-plugin/plugin.json`.

## Route-first policy hook

Codex loads the plugin's `hooks/hooks.json` automatically. Its SessionStart
handler injects a short route-first policy; it does not classify a task, start a
worker, or reject a prompt. Codex waits briefly for the handler at session start,
but later prompts do not run a routing hook. Review and trust the current hook
definition when Codex asks. The hook improves compliance but cannot replace the
model of an already-running parent turn.

For a guaranteed new-session entry, use the launcher:

```bash
plugins/codex-model-effort-router/bin/codex-route -- "<task>"
```

The level profiles under `agents/` are execution targets carrying per-level
developer instructions only. Model and effort always come from the router and
model map at runtime; direct agent calls fall back to the Codex default model.

Invoke the skill:

```text
/model-effort:route <task>
```

## CLI preflight

When the current Codex surface does not honor named plugin agents, run:

```bash
python3 scripts/router.py --platform codex --format command "<task>"
python3 scripts/router.py --platform codex --task-type design "<task>" --format command
```

Example single-stage output:

```bash
codex exec -m gpt-5.6-luna -c model_reasoning_effort=medium -c 'developer_instructions="..."' '<task>'
```

Example two-stage output (`architectural_refactoring` L3+, or `implementation` / `local_refactoring` at L5):

```bash
mkdir -p /tmp/codex-route-<run-id> && codex exec -m gpt-5.6-sol ... '<plan>' && codex exec -m gpt-5.6-luna ... '<execute>' && rm -rf /tmp/codex-route-<run-id>
```

The chain is success-dependent: the executor never runs after a failed plan
stage, and the run directory survives any failure for inspection. `--keep-plan`
preserves it even on success.

The CLI launcher starts a new process because a plugin cannot reliably replace the model of an already-running parent turn on every Codex surface. Codex CLI does not expose `--agent`, so this fallback applies the selected model and effort while the plugin skill handles named-agent delegation where available.

Before selecting that process, the router runs the native Codex CLI with fixed
`gpt-5.6-luna` / medium effort in a temporary read-only session and validates its JSON response.
Timeouts, process failures, and invalid output safely route to implementation /
L3. `--level` alone is a minimum; `--level` with an explicit `--task-type`
pins both axes and bypasses the preflight.

For a skill-selected route, save its JSON once and replay it with
`bin/codex-route --route-file <route.json>`; this executes the selected command
without another preflight classification. Two-stage replay stays in the parent pipeline,
which captures and validates planner stdout before installing the shared plan file.
The JSON `verification` object contains recommended and skipped check IDs with
reasons only; it does not execute checks. The selected executor receives its
recommended checks and reports each result or why it was not run. Route-file
replay ignores the JSON object and reuses only the stored execution steps.

Schema v7 is current. Schema v6 remains legacy and replay-compatible under the pre-v7 native
permission grammar; v7 records `facts`, `matched_rules`, `evidence`, and `risk_tier`,
while legacy v6 records `unresolved_facts` and `questions`.
`execution_strategy: "direct"` with
`orchestration_eligible` separately. `scripts/astra_adapter.py` is the unchanged
orchestration adapter, a caller-invoked isolated-worker boundary that revalidates worker
inputs and preserves original verified artifacts, not a launcher target. Direct v2-v7
route-file replay never invokes it.

## Customize

Edit `config/model-map.json`, run `python3 scripts/sync_bundle.py`, and keep
per-level developer instructions in the files under `agents/`.

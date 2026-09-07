# Codex Model Effort Router

## What it does

The skill classifies each task by `task_type` (implementation, design, review,
local_refactoring, architectural_refactoring) and difficulty (L1-L7), then
routes it through the `task_type × level` matrix in `config/model-map.json`:

- luna handles clearly defined coding work at lower levels
- terra handles L3-L4 implementation and local refactoring
- sol owns L5-L6 judgement and analysis
- astra handles L7 and Critical profiles
- architectural_refactoring at L3+ runs two stages: sol plans into a temporary
  plan file, then luna/terra executes it with the plan's validation commands

Security-related risk flags (security_sensitive, authentication,
authorization, payment) force an L6 floor before the matrix lookup.

## Test locally

From the bundle root, register the local marketplace and install the plugin:

```bash
codex plugin marketplace add /absolute/path/to/model-effort-router
codex plugin add model-effort@model-effort-router-bundle
```

The plugin manifest is `.codex-plugin/plugin.json`.

The seven profiles under `agents/` are execution targets carrying per-level
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
codex exec -m gpt-5.6-luna -c model_reasoning_effort=xhigh -c 'developer_instructions="..."' '<task>'
```

Example two-stage output (`architectural_refactoring` L3+):

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
L3. `--level` is a minimum; only `--level L7` plus an explicit `--task-type`
bypasses the preflight entirely.

For a skill-selected route, save its JSON once and replay it with
`bin/codex-route --route-file <route.json>`; this executes the selected command
without another preflight classification. Two-stage replay preserves its plan file.
The JSON `verification` object contains recommended and skipped check IDs with
reasons only; it does not execute checks. The selected executor receives its
recommended checks and reports each result or why it was not run. Route-file
replay ignores the JSON object and reuses only the stored execution steps.

Schema v3 records `execution_strategy: "direct"` and
`orchestration_eligible` separately. `scripts/astra_adapter.py` is available as
a caller-invoked isolated-worker boundary that revalidates worker inputs and
preserves original verified artifacts, not a launcher target. Direct v2 and v3
route-file replay never invokes it.

## Customize

Edit `config/model-map.json`, run `python3 scripts/sync_bundle.py`, and keep
per-level developer instructions in the seven files under `agents/`.

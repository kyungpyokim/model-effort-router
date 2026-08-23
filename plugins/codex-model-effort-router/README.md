# Codex Model Effort Router

## What it does

The skill classifies each task by `task_type` (implementation, design, review,
local_refactoring, architectural_refactoring) and difficulty (L1-L5), then
routes it through the `task_type × level` matrix in `config/model-map.json`:

- luna handles clearly defined coding work (implementation, local_refactoring)
- sol owns judgement and analysis (design, review)
- terra owns wide, long execution (L4-L5 implementation, migrations)
- architectural_refactoring at L3+ runs two stages: sol plans into a temporary
  plan file, then luna/terra executes it with the plan's validation commands

Security-related risk flags (security_sensitive, authentication,
authorization, payment) force an L4 floor before the matrix lookup.

## Test locally

From the bundle root, register the local marketplace and install the plugin:

```bash
codex plugin marketplace add /absolute/path/to/model-effort-router
codex plugin add model-effort@model-effort-router-bundle
```

The plugin manifest is `.codex-plugin/plugin.json`.

The five profiles under `agents/` are execution targets carrying per-level
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
`gpt-5.6-terra` / low effort in a temporary read-only session and validates its JSON response.
Timeouts, process failures, and invalid output safely route to implementation /
L3. `--level` is a minimum; `--level L5` plus an explicit `--task-type`
bypasses the preflight entirely.

## Customize

Edit `config/model-map.json`, run `python3 scripts/sync_bundle.py`, and keep
per-level developer instructions in the five files under `agents/`.

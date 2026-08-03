# Codex Model Effort Router

## What it does

The skill scores each task from L1 to L5 and delegates it to a Codex agent profile that pins both `model` and `model_reasoning_effort`.

## Test locally

From the bundle root, register the local marketplace and install the plugin:

```bash
codex plugin marketplace add /absolute/path/to/model-effort-router
codex plugin add model-effort-router@model-effort-router-bundle
```

The plugin manifest is `.codex-plugin/plugin.json`.

The five profiles under `agents/` are execution targets. The router skill
delegates to the matching profile; it never tries to change a running parent task.

Invoke the skill:

```text
/model-effort-router <task>
```

## CLI preflight

When the current Codex surface does not honor named plugin agents, run:

```bash
python3 scripts/router.py --platform codex --format command "<task>"
```

Example output:

```bash
codex exec -m gpt-5.6-sol -c model_reasoning_effort=xhigh -c 'developer_instructions="..."' '<task>'
```

The CLI launcher starts a new process because a plugin cannot reliably replace the model of an already-running parent turn on every Codex surface. Codex CLI does not expose `--agent`, so this fallback applies the selected model and effort while the plugin skill handles named-agent delegation where available.

Before selecting that process, the router runs the native Codex CLI with fixed
`gpt-5.6-terra` / low effort in a temporary read-only session and validates its JSON response.
Timeouts, process failures, and invalid output safely route to L3. `--level`
is a minimum; only `--level L5` bypasses the preflight.

## Customize

Edit `config/model-map.json` and the five files under `agents/` together.

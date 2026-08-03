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
codex -m gpt-5.6-sol -c model_reasoning_effort=xhigh exec '<task>'
```

The CLI launcher starts a new process because a plugin cannot reliably replace the model of an already-running parent turn on every Codex surface.

Before selecting that process, the router runs fixed `gpt-5.6-terra` / low
effort in a temporary read-only Codex session and validates its JSON response.
Timeouts, process failures, and invalid output safely route to L3. `--level`
is a minimum; only `--level L5` bypasses the preflight.

## Customize

Edit `config/model-map.json` and the five files under `agents/` together.

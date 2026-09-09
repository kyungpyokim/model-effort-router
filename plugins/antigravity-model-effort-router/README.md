# Antigravity Model Effort Router

## Install

From a local directory:

```bash
agy plugin install /absolute/path/to/antigravity-model-effort-router
```

From a Git repository after publishing:

```bash
agy plugin install https://github.com/<owner>/<repo>
```

## Use inside Antigravity

```text
/route <task>
```

This classifies and explains the route, but it does not pretend to replace the model of the already-running session.

The plugin includes L1-L7 and Critical agents under `agents/`. `agy-route` starts a new
session with the matching `--agent` and account-available model.

## Execute with automatic model selection

```bash
./bin/agy-route --interactive -- "<task>"
```

For one-shot mode:

```bash
./bin/agy-route -- "<task>"
```

To execute an already-generated route without classifying or detecting models again:

```bash
./bin/agy-route --route-file /absolute/path/to/route.json
```

Replay preserves `steps[].command`, including the interactive choice saved when
generating JSON with `--interactive`. Two-stage runs remain noninteractive and
start the executor only after the planner succeeds.

The router first classifies with native `agy` using fixed
`Gemini 3.8 Flash (Medium)`, print mode, and an isolated sandboxed plan
directory. It disables slash-command expansion and validates native
schema-constrained JSON. The launcher detects available models with `agy models`
before classification and starts the selected profile. Classifier failures
safely select L3.
In Antigravity, effort is represented in names such as `Gemini ... Flash (Low)` or `Claude ... (Thinking)` rather than a separate `--effort` flag.

Route-file replay accepts existing v2 payloads. Schema v3 records direct-only
`execution_strategy` and future Astra `orchestration_eligible` metadata; it
does not enable orchestration on Antigravity. `scripts/astra_adapter.py` is a
caller-invoked boundary that revalidates worker inputs and preserves original
verified artifacts; direct v2 and v3 route-file replay never invokes it.

## Customize

Edit the ordered regular expressions and fallbacks under `platforms.antigravity` in `config/model-map.json`.

## Validate

```bash
agy plugin validate .
```

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

## Execute with automatic model selection

```bash
./bin/agy-route --interactive -- "<task>"
```

For one-shot mode:

```bash
./bin/agy-route -- "<task>"
```

The launcher calls `agy models`, matches the first available model for the selected level, then starts `agy --model ...`. In Antigravity, effort is represented in names such as `Gemini ... Flash (Low)` or `Claude ... (Thinking)` rather than a separate `--effort` flag.

## Customize

Edit the ordered regular expressions and fallbacks under `platforms.antigravity` in `config/model-map.json`.

## Validate

```bash
agy plugin validate .
```

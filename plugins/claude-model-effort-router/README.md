# Claude Code Model Effort Router

## Install from the bundle marketplace

From Claude Code:

```text
/plugin marketplace add /absolute/path/to/model-effort-router
/plugin install model-effort-router@model-effort-router-bundle
/reload-plugins
```

## Test without installation

```bash
claude --plugin-dir .
```

Then invoke:

```text
/model-effort-router:model-effort-router <task>
```

The router preflights each task with fixed `gpt-5.6-terra` / low effort and
delegates to one of five plugin agents. The JSON response is schema-validated;
failure safely selects L3. Each agent pins `model` and `effort` in frontmatter.
The preflight requires an installed, authenticated Codex CLI.

## Validate

```bash
claude plugin validate .
```

## Deterministic CLI fallback

```bash
python3 scripts/router.py --platform claude-code --format command "<task>"
```

This prints a command such as:

```bash
claude --model opus --effort xhigh -p '<task>'
```

`--level` is a minimum, so L1-L4 still run preflight; `--level L5` bypasses it.

## Customize

Edit `config/model-map.json` and the five Markdown files under `agents/` together. Claude Code may clamp an unsupported effort to the highest supported level for the selected model.

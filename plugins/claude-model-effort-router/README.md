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

The router itself runs cheaply, scores the task, and delegates to one of five plugin agents. Each agent pins `model` and `effort` in frontmatter.

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

## Customize

Edit `config/model-map.json` and the five Markdown files under `agents/` together. Claude Code may clamp an unsupported effort to the highest supported level for the selected model.

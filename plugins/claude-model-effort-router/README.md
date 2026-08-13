# Claude Code Model Effort Router

## Install from the bundle marketplace

From Claude Code:

```text
/plugin marketplace add /absolute/path/to/model-effort-router
/plugin install model-effort@model-effort-router-bundle
/reload-plugins
```

## Test without installation

```bash
claude --plugin-dir .
```

Then invoke:

```text
/model-effort:route <task>
```

The router preflights each task with native `claude-sonnet-5` / low. Claude's
JSON-schema output is read from its `structured_output` result field. Safe mode,
no tools, plan permissions, no session persistence, and a temporary working
directory isolate the classifier. Failure safely selects L3. Each agent pins
`model` and `effort` in frontmatter.

The deterministic launcher starts a new session with both `--agent` and the
selected model/effort; it never tries to change the current session.

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
claude --agent level-4-advanced --model opus --effort xhigh -p '<task>'
```

`--level` is a minimum, so L1-L4 still run preflight; `--level L5` bypasses it.

## Customize

Edit `config/model-map.json` and the five Markdown files under `agents/` together. Claude Code may clamp an unsupported effort to the highest supported level for the selected model.

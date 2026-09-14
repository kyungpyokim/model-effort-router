# Claude Code Model Effort Router

## Install from the bundle marketplace

From Claude Code:

```text
/plugin marketplace add /absolute/path/to/model-effort-router
/plugin install model-effort@model-effort-router-bundle
/reload-plugins
```

## Route-first policy hook

Claude Code loads the plugin's `hooks/hooks.json` automatically. Its SessionStart
handler injects a short route-first policy telling the session to invoke
`model-effort:route` before substantive coding work; it does not classify a task,
start a worker, or block a prompt. The hook improves compliance but cannot force a
skill call, and stronger instructions from other plugins can still win. Invoke
`/model-effort:route <task>` directly when routing must happen.

## Test without installation

```bash
claude --plugin-dir .
```

Then invoke:

```text
/model-effort:route <task>
```

The router preflights each task with native `claude-haiku-4-5`, then uses
`claude-sonnet-5` / medium once when `needs_context` is true. Claude's JSON-schema output is
read from its `structured_output` result field. Safe mode,
no tools, plan permissions, no session persistence, and a temporary working
directory isolate the classifier. Failure safely selects L3. Each agent pins
`model` and `effort` in frontmatter.

The v4 execution matrix is:

| task type | L1 | L2 | L3 | L4 | L5 | L6 | L7 | Critical |
|---|---|---|---|---|---|---|---|---|
| implementation / local_refactoring | haiku | haiku | sonnet med | sonnet high | fable med (opus med) | fable high (opus high) | fable xhigh (opus xhigh) | fable max (opus max) |
| design / review | haiku | opus low | opus med | opus high | fable high (opus high) | fable xhigh (opus xhigh) | fable xhigh (opus xhigh) | fable max (opus max) |
| architectural_refactoring | haiku | opus med | fable high -> sonnet med | fable xhigh -> sonnet high | fable xhigh -> sonnet high | fable xhigh -> fable high | fable max -> fable xhigh | fable max (opus max) |

Fable is the primary candidate and Opus is its availability fallback; `A -> B`
is the success-dependent planner-to-implementer chain. Read-only design and
review use `files_touched: 0`; files only read for context do not count.

Inside a session, the route skill delegates each stored step with the Agent tool
(`steps[].agent.subagent_type` + `steps[].agent.model`), so the executor keeps the
session's working directory and edit permissions. The Agent tool cannot set effort, so
the subagent is an `effort-*` agent whose frontmatter pins the matrix effort; the level
instructions travel at the top of the prompt.

From a terminal, `bin/claude-route` starts an interactive session with the selected
model/effort and puts the matching level agent's instructions at the top of the prompt,
so it works without the plugin installed. `--print` forces `claude -p`, which runs with
default permissions and cannot edit files unless your settings allow it.

Route-file replay accepts v2-v4 payloads. Schema v4 adds `facts`,
`matched_rules`, `needs_context`, and `evidence` alongside direct-only
`execution_strategy` and future Astra `orchestration_eligible` metadata; it
does not enable orchestration on Claude Code. `scripts/astra_adapter.py` is a
caller-invoked boundary that revalidates worker inputs and preserves original
verified artifacts; direct v2-v4 route-file replay never invokes it.

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
claude --model claude-sonnet-5 --effort high -p '<level-4-complex instructions> <task>'
```

`--level` alone is a minimum; `--level` with an explicit `--task-type`
pins both axes and bypasses the preflight.

## Customize

Edit `config/model-map.json` and the agent Markdown files under `agents/` together. Claude Code may clamp an unsupported effort to the highest supported level for the selected model.

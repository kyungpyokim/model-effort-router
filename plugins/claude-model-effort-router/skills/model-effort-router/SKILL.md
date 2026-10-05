---
name: model-effort-router
description: Advisory notes and the mer CLI for routing a development request to a Claude model and effort. Use when a [model-effort-router] note was injected or the user asks which model or effort to use.
---

# Model-Effort Router (Claude Code)

The plugin imports the shared runtime from
`${XDG_DATA_HOME:-~/.local/share}/model-effort-router/runtime`. If it is
missing, install it from a matching repository checkout with
`python3 scripts/install_core.py`. For a checkout, use
`MER_CORE_PATH="$PWD"`.

The UserPromptSubmit hook may add a `[model-effort-router]` note: difficulty level, risk flags, a recommended model and effort, plan-first advice and, for high-risk work, a recommendation for an independent review. It is advice only: nothing is enforced and you do not spawn subagents for it.

- Mention the recommendation to the user briefly when it differs from the current model/effort; they switch with `/model` and `/effort`.
- Follow plan-first advice by writing a short plan before changing code.
- For routed work the user can run the whole task through the `mer` CLI, which runs one `claude -p` session at the recommended profile, runs the Test Gate, escalates the same session (`--resume`) on failure and adds an independent read-only review when required: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/mer run '<the task>'`.
- To start an interactive Claude Code session already at the routed model/effort: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/mer chat '<the task>'` (routing happens once, at the start; later prompts are not re-routed).
- An independent review of the current diff only: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/mer run --review-profile <tier:effort from the advice> 'review only: check the current diff for <the task>'`. Single-quote requests (write ' as '\'') so the shell expands nothing.
- The Test Gate alone: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/mer-gate`. A check with status `not_run` is not passed; report it as not run.
- Override on the first line of a prompt: `/router off`, `/router session=frontier:high`.

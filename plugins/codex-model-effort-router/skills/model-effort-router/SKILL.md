---
name: model-effort-router
description: Automatic per-turn model routing and the mer CLI for development requests. Use when a [model-effort-router] note was injected or the user asks which model/effort to use.
---

# Model-Effort Router

The plugin imports the shared runtime from
`${XDG_DATA_HOME:-~/.local/share}/model-effort-router/runtime`. If it is
missing, install it from a matching repository checkout with
`python3 scripts/install_core.py`. For a checkout, use
`MER_CORE_PATH="$PWD"`.

The UserPromptSubmit hook classifies routed requests and, when Codex's experimental `step_model_switching` feature is enabled, applies Jev's selected model and reasoning effort to the current turn. The hook adds a `[model-effort-router]` note with difficulty, risk flags, plan-first advice and, for high-risk work, a recommendation for an independent review. If the active-turn update is unavailable, the note gives an advisory model/effort recommendation instead. This changes only the current turn, never future thread defaults. The hook never blocks requests or asks you to spawn subagents.

Automatic turn updates require a Codex build with `step_model_switching` support, the feature enabled in Codex configuration, and a Codex restart after changing that setting.

- Mention the recommendation to the user briefly when it differs from the current model/effort; they switch with `/model`.
- Follow plan-first advice by writing a short plan before changing code.
- For routed work the user can run the whole task through the `mer` CLI, which runs one session at the recommended profile, runs the Test Gate, escalates the same session on failure and adds an independent review when required: `python3 <plugin root>/bin/mer run "<the task>"`.
- To start an interactive Codex session already at the routed model/effort: `python3 <plugin root>/bin/mer chat '<the task>'` (routing happens once, at the start; later prompts in that session are not re-routed).
- An independent review of the current diff only: `python3 <plugin root>/bin/mer run --review-profile <tier:effort from the advice> 'review only: check the current diff for <the task>'`. Single-quote requests (write ' as '\'') so the shell expands nothing.
- The Test Gate alone: `python3 <plugin root>/bin/mer-gate`. A check with status `not_run` is not passed; report it as not run.
- Override on the first line of a prompt: `/router off`, `/router session=frontier:high`.

---
name: model-effort-router
description: Route development requests to a role, effort, and Codex model; provide Main with Subagent guidance.
---

# Model Effort Router for Codex

The plugin imports the shared runtime from `${XDG_DATA_HOME:-~/.local/share}/model-effort-router/runtime`. Install a matching checkout with `python3 scripts/install_core.py`; for development set `MER_CORE_PATH="$PWD"`.

The UserPromptSubmit hook classifies eligible development requests into a role and effort and adds a `[model-effort-router]` note with the mapped model and a compact Context Packet. It never changes the current turn's model/settings and never creates a Subagent. Main retains the conversation and decides which individual Subagent work is needed.

- Roles `implementation`, `fix`, `lint`, and `test` map to the execution model (`gpt-6-luna` by default). `plan`, `design`, `review`, and `analysis` map to reasoning (`gpt-6.1-sol` by default).
- Effort is `low`, `medium`, `high`, or `xhigh`. Risk floors can raise sensitive review/design work to at least `high`; they do not change role or model lane.
- Give a Subagent only the needed Context Packet: task, context, decisions, constraints, relevant files, and expected result. For review use goal, decisions, constraints, diff, and verification. Do not forward full conversation or private agent reasoning by default.
- `python3 <plugin root>/bin/mer route --json '<task>'` prints the route. Main can provide a phase-specific `--role` and `--effort` together when it has already chosen the phase.
- `python3 <plugin root>/bin/mer run --role implementation --effort high '<task>'` runs one external worker. It does not run a Gate, escalate, or add an automatic review. Reasoning roles use read-only execution.
- `mer chat`, L1-L5 flags, tier overrides, and automatic escalation/review options were removed. Replace them with `mer route` and a Main-selected Subagent. Replace `/router session=...` with `/router role=<role> effort=<effort>`.
- If classification providers all fail, CLI routing reports an error; the hook fails open so the user request continues without a route note.

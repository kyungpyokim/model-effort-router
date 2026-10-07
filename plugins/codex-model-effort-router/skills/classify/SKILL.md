---
name: classify
description: Route development requests to a role, effort, and Codex model; provide Main with Subagent guidance.
---

# Classify for Codex

The plugin imports the shared runtime from `${XDG_DATA_HOME:-~/.local/share}/model-effort-router/runtime`. Install a matching checkout with `python3 scripts/install_core.py`; for development set `MER_CORE_PATH="$PWD"`.

The UserPromptSubmit hook classifies eligible development requests and adds a `[model-effort-router]` note. It does not read Main's conversation or populate a complete Context Packet. It never changes the current turn's model/settings or creates a Subagent. Main is responsible for following the route: fill the packet from the current request and relevant conversation, dispatch the matching host-native Subagent, then integrate its result.

This integration is advisory-only. Codex hooks cannot force Main to delegate read-only analysis, and the current hook signals do not provide a verified dispatch-to-child identity bridge for an edit gate. Do not claim universal code-edit enforcement or runtime model/effort compliance; Main must use the recommended role/model/effort when dispatching and treat those settings as advice unless the host exposes enforceable signals.

- Roles `implementation`, `fix`, `lint`, and `test` map to execution (`gpt-6-luna` by default); `plan`, `design`, `review`, and `analysis` map to reasoning (`gpt-6.1-sol` by default).
- Effort is `low`, `medium`, `high`, `xhigh`, or `max`. Risk floors can raise sensitive review/design work to at least `high`; they do not change role or model lane.
- Give each worker only the needed, populated Context Packet: task, context, decisions, constraints, relevant files, and expected result. Do not forward the full conversation or private reasoning by default.
- For nontrivial code changes, complete and integrate implementation first, then use the `review` skill. It guides a separate Subagent to inspect the actual diff and fix actionable findings. Skip docs-only and trivial mechanical edits.
- `mer route --role <role> --effort <effort>` selects the worker's model only; Main keeps its current model and settings. `mer run` is a separate one-worker path and cannot read Main's conversation; include needed context in its explicit task input. `mer run --role review` is read-only and cannot fix findings.
- `python3 <plugin root>/bin/mer route --json '<task>'` prints the route. Main can set a phase-specific `--role` and `--effort` when it has chosen the phase.
- `python3 <plugin root>/bin/mer run --role implementation --effort high '<task>'` runs one external worker. It does not run a Gate, escalate, or add an automatic review. Reasoning roles are read-only.
- When a run changes repository paths, its output includes a `change` summary: `door` (`one-way` for data migration, data loss, or payment risk; otherwise `two-way`) and estimated `blast_radius` (`local` or `broad`). Treat blast radius as a path-based estimate and inspect the actual changes.
- `mer chat`, L1-L5 flags, tier overrides, and automatic escalation/review options were removed. Replace them with `mer route` and Main-selected Subagents. Replace `/router session=...` with `/router role=<role> effort=<effort>`.
- If all classification providers fail, CLI routing reports an error; the hook fails open so the user request continues without a route note.

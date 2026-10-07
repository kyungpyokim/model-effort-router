---
name: classify
description: Route development requests to a role, effort, and Claude model; provide Main with Subagent guidance.
---

# Classify for Claude Code

The plugin imports the shared runtime from `${XDG_DATA_HOME:-~/.local/share}/model-effort-router/runtime`. Install a matching checkout with `python3 scripts/install_core.py`; for development set `MER_CORE_PATH="$PWD"`.

The UserPromptSubmit hook classifies eligible development requests and adds a `[model-effort-router]` note. It does not read Main's conversation or populate a complete Context Packet. It neither changes Main's model nor launches a Subagent. Main fills the packet from the current request and relevant conversation, then uses the host-native Subagent invocation.

- `implementation`, `fix`, `lint`, and `test` map to execution (`claude-fable-5-1` by default); `plan`, `design`, `review`, and `analysis` map to reasoning (`claude-fable-5-1` by default).
- Effort is `low`, `medium`, `high`, or `xhigh`. Sensitive review/design work has a `high` minimum when risk is detected. Unsupported requested effort returns a routing error rather than silently lowering effort.
- Give each worker only the needed, populated Context Packet: task, context, decisions, constraints, relevant files, and expected result. Do not forward the full conversation or private reasoning by default.
- For nontrivial code changes, complete and integrate implementation first, then use the `review` skill. It guides a separate Subagent to inspect the actual diff and fix actionable findings. Skip docs-only and trivial mechanical edits.
- `mer route --role <role> --effort <effort>` selects the worker's model only; Main keeps its current model and settings. `mer run` is a separate one-worker path and cannot read Main's conversation; include needed context in its explicit task input. `mer run --role review` is read-only and cannot fix findings.
- `python3 ${CLAUDE_PLUGIN_ROOT}/bin/mer route --json '<task>'` prints the route. Main may provide an explicit phase with `--role` and `--effort` together.
- `python3 ${CLAUDE_PLUGIN_ROOT}/bin/mer run --role implementation --effort high '<task>'` runs one external worker. It does not run a Gate, escalate, or add an automatic review. Reasoning roles are read-only.
- When a run changes repository paths, its output includes a `change` summary: `door` (`one-way` for data migration, data loss, or payment risk; otherwise `two-way`) and estimated `blast_radius` (`local` or `broad`). Treat blast radius as a path-based estimate and inspect the actual changes.
- `mer chat`, L1-L5 and tier/profile overrides, and automatic escalation/review options were removed. Use `mer route` and Main-selected Subagents. Replace `/router session=...` with `/router role=<role> effort=<effort>`.
- If all classification providers fail, CLI routing reports an error; the hook fails open so the request continues without a route note.

---
name: model-effort-router
description: Route development requests to a role, effort, and Claude model; provide Main with Subagent guidance.
---

# Model Effort Router for Claude Code

The plugin imports the shared runtime from `${XDG_DATA_HOME:-~/.local/share}/model-effort-router/runtime`. Install a matching checkout with `python3 scripts/install_core.py`; for development set `MER_CORE_PATH="$PWD"`.

The UserPromptSubmit hook classifies eligible development requests into role and effort and adds a `[model-effort-router]` note with the mapped model and a compact Context Packet. The note is guidance for Main to invoke a host-native Subagent. The hook neither changes Main's model nor launches a Subagent.

- `implementation`, `fix`, `lint`, and `test` map to execution (`claude-sonnet-5-5` by default); `plan`, `design`, `review`, and `analysis` map to reasoning (`claude-opus-5-5` by default).
- Effort is `low`, `medium`, `high`, or `xhigh`. Sensitive review/design work has a `high` minimum when risk is detected. Requested effort is not silently reduced to an unsupported value; configure a capable model or receive a routing error.
- Pass only the context needed by the task. Standard packets contain task, context, decisions, constraints, relevant files, and expected result. Review packets contain goal, decisions, constraints, diff, and verification, without implementation-agent reasoning.
- `python3 ${CLAUDE_PLUGIN_ROOT}/bin/mer route --json '<task>'` shows the route. Main may provide an explicit phase with `--role` and `--effort` together.
- `python3 ${CLAUDE_PLUGIN_ROOT}/bin/mer run --role review --effort high '<task>'` runs one read-only worker request. No Gate, escalation, or automatic follow-up review runs.
- When a run changes repository paths, its output includes a `change` summary: `door` (`one-way` for data migration, data loss, or payment risk; otherwise `two-way`) and estimated `blast_radius` (`local` or `broad`). Treat blast radius as a path-based estimate and review the actual changes.
- `mer chat`, L1-L5 and tier/profile overrides, and automatic escalation/review options were removed. Use `mer route` and Main's Subagent tool instead. Replace `/router session=...` with `/router role=<role> effort=<effort>`.
- If all classifier providers fail, CLI routing reports an error; the hook fails open and lets the request continue.

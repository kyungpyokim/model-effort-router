---
name: model-effort-router
description: Route development requests to a role, effort, and Claude model; provide Main with Subagent guidance.
---

# Model Effort Router for Claude Code

The plugin imports the shared runtime from `${XDG_DATA_HOME:-~/.local/share}/model-effort-router/runtime`. Install a matching checkout with `python3 scripts/install_core.py`; for development set `MER_CORE_PATH="$PWD"`.

The UserPromptSubmit hook classifies eligible development requests into role and effort and adds a `[model-effort-router]` note with the mapped model and Context Packet fields/instructions. It does not read Main's conversation or supply a completed packet. Main uses the current request and relevant conversation to populate the packet and includes it in the host-native Subagent invocation. The hook neither changes Main's model nor launches a Subagent.

- `implementation`, `fix`, `lint`, and `test` map to execution (`claude-sonnet-5-5` by default); `plan`, `design`, `review`, and `analysis` map to reasoning (`claude-opus-5-5` by default).
- Effort is `low`, `medium`, `high`, or `xhigh`. Sensitive review/design work has a `high` minimum when risk is detected. Requested effort is not silently reduced to an unsupported value; configure a capable model or receive a routing error.
- Pass only the needed, populated context. Standard packets contain task, context, decisions, constraints, relevant files, and expected result. Review packets contain goal, decisions, constraints, actual diff, and verification status/results; mark checks that were not run as not run. Omit the full conversation and private implementation reasoning.
- For nontrivial code changes, delegate a separate host-native Subagent with workspace write access to review the diff and fix actionable findings, especially for security, data-loss, payment, or other high-impact changes. Skip docs-only and trivial mechanical edits. The Subagent runs relevant verification and reports changes and unresolved issues; request another review only after meaningful code changes.
- `mer route --role review --effort <effort>` selects the Subagent's model only; Main stays on its current model and settings. `mer run --role review` is read-only and cannot make fixes, so use a native Subagent for review-and-fix.
- `mer run` is a separate one-worker path and cannot read Main's conversation; include needed context in its explicit task input.
- `python3 ${CLAUDE_PLUGIN_ROOT}/bin/mer route --json '<task>'` shows the route. Main may provide an explicit phase with `--role` and `--effort` together.
- `python3 ${CLAUDE_PLUGIN_ROOT}/bin/mer run --role review --effort high '<task>'` runs one read-only worker request; it cannot make fixes. No Gate, escalation, or automatic follow-up review runs.
- When a run changes repository paths, its output includes a `change` summary: `door` (`one-way` for data migration, data loss, or payment risk; otherwise `two-way`) and estimated `blast_radius` (`local` or `broad`). Treat blast radius as a path-based estimate and review the actual changes.
- `mer chat`, L1-L5 and tier/profile overrides, and automatic escalation/review options were removed. Use `mer route` and Main's Subagent tool instead. Replace `/router session=...` with `/router role=<role> effort=<effort>`.
- If all classifier providers fail, CLI routing reports an error; the hook fails open and lets the request continue.

---
name: mer
description: Route development requests to a role, effort, and Codex model; provide Main with Subagent guidance.
---

# Model Effort Router for Codex

The plugin imports the shared runtime from `${XDG_DATA_HOME:-~/.local/share}/model-effort-router/runtime`. Install a matching checkout with `python3 scripts/install_core.py`; for development set `MER_CORE_PATH="$PWD"`.

The UserPromptSubmit hook classifies eligible development requests into a role and effort and adds a `[model-effort-router]` note with the mapped model and Context Packet fields/instructions. It does not read Main's conversation or supply a completed packet. Main uses the current request and relevant conversation to populate the packet and includes it in the host-native Subagent invocation. The hook never changes the current turn's model/settings and never creates a Subagent.

- Roles `implementation`, `fix`, `lint`, and `test` map to the execution model (`gpt-6-luna` by default). `plan`, `design`, `review`, and `analysis` map to reasoning (`gpt-6.1-sol` by default).
- Effort is `low`, `medium`, `high`, or `xhigh`. Risk floors can raise sensitive review/design work to at least `high`; they do not change role or model lane.
- Give a Subagent only the needed, populated Context Packet: task, context, decisions, constraints, relevant files, and expected result. For review use goal, decisions, constraints, actual diff, and verification status/results; mark checks that were not run as not run. Do not forward full conversation or private agent reasoning by default.
- For nontrivial code changes, delegate a separate host-native Subagent with workspace write access to review the diff and fix actionable findings, especially for security, data-loss, payment, or other high-impact changes. Skip docs-only and trivial mechanical edits. The Subagent runs relevant verification and reports changes and unresolved issues; request another review only after meaningful code changes.
- `mer route --role review --effort <effort>` selects the Subagent's model only; Main stays on its current model and settings. `mer run --role review` is read-only and cannot make fixes, so use a native Subagent for review-and-fix.
- `mer run` is a separate one-worker path and cannot read Main's conversation; include needed context in its explicit task input.
- `python3 <plugin root>/bin/mer route --json '<task>'` prints the route. Main can provide a phase-specific `--role` and `--effort` together when it has already chosen the phase.
- `python3 <plugin root>/bin/mer run --role implementation --effort high '<task>'` runs one external worker. It does not run a Gate, escalate, or add an automatic review. Reasoning roles use read-only execution.
- When a run changes repository paths, its output includes a `change` summary: `door` (`one-way` for data migration, data loss, or payment risk; otherwise `two-way`) and estimated `blast_radius` (`local` or `broad`). Treat blast radius as a path-based estimate and review the actual changes.
- `mer chat`, L1-L5 flags, tier overrides, and automatic escalation/review options were removed. Replace them with `mer route` and a Main-selected Subagent. Replace `/router session=...` with `/router role=<role> effort=<effort>`.
- If classification providers all fail, CLI routing reports an error; the hook fails open so the user request continues without a route note.

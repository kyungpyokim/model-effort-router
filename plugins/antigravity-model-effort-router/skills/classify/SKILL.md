---
name: classify
description: Classify an Antigravity development request and provide role/effort advice to Main.
---

# Model Effort Router for Antigravity

The plugin imports the shared runtime from `${XDG_DATA_HOME:-~/.local/share}/model-effort-router/runtime`. Install a matching checkout with `python3 scripts/install_core.py`; for development set `MER_CORE_PATH="$PWD"`.

The hook may classify eligible requests into role and effort and provide a route note to Main. It does not change Main's model, create a Subagent, or execute routed work. Antigravity worker execution remains unsupported because the host's Subagent execution isolation is unverified; use `mer route` for classification and follow only host-supported execution paths.

Roles are `implementation`, `fix`, `lint`, `test`, `plan`, `design`, `review`, and `analysis`. Execution roles map to the configured execution lane; reasoning roles map to reasoning. Efforts are `low`, `medium`, `high`, and `xhigh`; Antigravity's default configured supported range is `medium` and `high`, so an unsupported mapping returns a routing error rather than silently lowering effort.

Main retains context and decides which phases to delegate. The hook provides packet fields and instructions, not a completed packet from Main's conversation. Main uses the current request and relevant conversation to populate a concise Context Packet (task, context, decisions, constraints, relevant files, expected result) and includes it in the host-native Subagent invocation. Review packets contain only goal, decisions, constraints, actual diff, and verification status/results; mark checks that were not run as not run, and omit the full conversation and private implementation reasoning. For nontrivial code changes, delegate a separate host-native Subagent with workspace write access to review the diff and fix actionable findings, especially for security, data-loss, payment, or other high-impact changes. Use only host-supported write-capable Subagent execution; do not call unsupported `mer run`. `mer route --role review --effort <effort>` selects the Subagent's model only; Main stays on its current model and settings. Skip docs-only and trivial mechanical edits. The Subagent runs relevant verification and reports changes and unresolved issues; request another review only after meaningful code changes. The removed `mer chat`, automatic escalation, Gate, and automatic review workflow have migrated to `mer route` and explicit Main orchestration. Classifier exhaustion fails open in hooks.

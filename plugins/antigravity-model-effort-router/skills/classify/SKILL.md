---
name: classify
description: Classify an Antigravity development request and provide role/effort advice to Main.
---

# Classify for Antigravity

The plugin imports the shared runtime from `${XDG_DATA_HOME:-~/.local/share}/model-effort-router/runtime`. Install a matching checkout with `python3 scripts/install_core.py`; for development set `MER_CORE_PATH="$PWD"`.

The hook may classify eligible requests and add a route note. It does not change Main's model or execute routed work. Antigravity worker execution remains unsupported because Subagent execution isolation is unverified; use `mer route` for classification and follow only host-supported execution paths.

- Roles are `implementation`, `fix`, `lint`, `test`, `plan`, `design`, `review`, and `analysis`. Execution roles map to the configured execution lane; reasoning roles map to reasoning.
- Efforts are `low`, `medium`, `high`, and `xhigh`. The default configured supported range is `medium` and `high`; unsupported mappings return a routing error rather than silently lowering effort.
- Main retains context and populates the Context Packet (task, context, decisions, constraints, relevant files, expected result) for any host-supported worker.
- When a nontrivial implementation has been integrated, use the `review` skill only if the host provides a supported write-capable reviewer. The current Antigravity worker path is unverified; do not use `mer run` or claim an independent review occurred.
- The removed `mer chat`, automatic escalation, Gate, and automatic review workflow are replaced by `mer route` and explicit Main orchestration. Classifier exhaustion fails open in hooks.

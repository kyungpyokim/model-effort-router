---
name: model-effort-router
description: Classify an Antigravity development request and provide role/effort advice to Main.
---

# Model Effort Router for Antigravity

The plugin imports the shared runtime from `${XDG_DATA_HOME:-~/.local/share}/model-effort-router/runtime`. Install a matching checkout with `python3 scripts/install_core.py`; for development set `MER_CORE_PATH="$PWD"`.

The hook may classify eligible requests into role and effort and provide a route note to Main. It does not change Main's model, create a Subagent, or execute routed work. Antigravity worker execution remains unsupported because the host's Subagent execution isolation is unverified; use `mer route` for classification and follow only host-supported execution paths.

Roles are `implementation`, `fix`, `lint`, `test`, `plan`, `design`, `review`, and `analysis`. Execution roles map to the configured execution lane; reasoning roles map to reasoning. Efforts are `low`, `medium`, `high`, and `xhigh`; Antigravity's default configured supported range is `medium` and `high`, so an unsupported mapping returns a routing error rather than silently lowering effort.

Main retains context and decides which phases to delegate. Pass a concise Context Packet (task, context, decisions, constraints, relevant files, expected result); review should receive only goal, decisions, constraints, diff, and verification. The removed `mer chat`, L1-L5 tiers, automatic escalation, Gate, and review workflow have migrated to `mer route` and explicit Main orchestration. Classifier exhaustion fails open in hooks.

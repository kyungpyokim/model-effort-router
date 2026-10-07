---
name: classify
description: Classify an Antigravity development request and provide role/effort advice to Main.
---

# Classify for Antigravity

The plugin imports the shared runtime from `${XDG_DATA_HOME:-~/.local/share}/model-effort-router/runtime`. Install a matching checkout with `python3 scripts/install_core.py`; for development set `MER_CORE_PATH="$PWD"`.

The `PreInvocation` hook adds the model and highest supported effort from `models.antigravity.execution` as guidance. It cannot change Main's model, classify the current request, or launch a Subagent. Antigravity's documented Subagent controls do not guarantee an exact model slug or effort; describe the configured profile as a preference unless the host confirms it. Main classifies the request with `mer route` or direct judgment, then uses Antigravity's native Subagent workflow when delegation is useful.

- Roles are `implementation`, `fix`, `lint`, `test`, `plan`, `design`, `review`, and `analysis`. Execution roles map to the configured execution lane; reasoning roles map to reasoning.
- Efforts are `low`, `medium`, `high`, `xhigh`, and `max`. The default configured supported range is `medium` and `high`; unsupported mappings return a routing error rather than silently lowering effort.
- Main retains context and populates the Context Packet (task, context, decisions, constraints, relevant files, expected result) for a native Subagent. Do not forward the full conversation or private reasoning.
- For a nontrivial implementation, integrate the implementation Subagent's changes, then use the `review` skill in a separate write-capable Subagent call.
- `mer run` is unsupported on this host. `mer route` and skills guide explicit Main orchestration; the hook fails open if its config or shared runtime is unavailable.

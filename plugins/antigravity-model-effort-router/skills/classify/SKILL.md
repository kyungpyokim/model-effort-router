---
name: classify
description: Route an Antigravity request to a role, effort, and model profile.
---

# Classify for Antigravity

The plugin imports the shared runtime from `${XDG_DATA_HOME:-~/.local/share}/model-effort-router/runtime`. Install a matching checkout with `python3 scripts/install_core.py`; for development set `MER_CORE_PATH="$PWD"`.

The `PreInvocation` hook classifies the latest user request and recommends the model and effort. If the transcript is unreadable, it recommends the configured execution profile. The hook cannot change the active model. Antigravity's controls do not guarantee an exact model slug or effort, so treat the recommendation as advisory.

- Roles are `implementation`, `fix`, `lint`, `test`, `plan`, `design`, `review`, and `analysis`. The first four use the execution lane; the rest use reasoning.
- Efforts are `low`, `medium`, `high`, `xhigh`, and `max`. The default supported range is `medium` and `high`; unsupported mappings return a routing error.
- Use `mer route --role <role> --effort <effort>` to select an explicit profile. Both values are required. `mer run` is no longer supported.

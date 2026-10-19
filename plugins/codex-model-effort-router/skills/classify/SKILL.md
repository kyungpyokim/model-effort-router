---
name: classify
description: Route a development request to a role, effort, and Codex model.
---

# Classify for Codex

The plugin imports the shared runtime from `${XDG_DATA_HOME:-~/.local/share}/model-effort-router/runtime`. Install a matching checkout with `python3 scripts/install_core.py`; for development set `MER_CORE_PATH="$PWD"`.

The UserPromptSubmit hook classifies eligible requests and recommends the role, model, and effort. It does not change the active turn's settings or execute work.

- Roles `implementation`, `fix`, `lint`, and `test` use the execution lane (`gpt-6-luna` by default); `plan`, `design`, `review`, and `analysis` use the reasoning lane (`gpt-6.1-sol` by default).
- Effort is `low`, `medium`, `high`, `xhigh`, or `max`. Security-sensitive review/design requests may have a `high` minimum; this does not change the role or lane.
- Use `mer route --role <role> --effort <effort>` to select an explicit profile. Both values are required.
- `python3 <plugin root>/bin/mer route --json '<task>'` prints a route. Classifier failures leave the host request unblocked; the CLI reports them as errors.

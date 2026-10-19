---
name: classify
description: Route a development request to a role, effort, and Claude model.
---

# Classify for Claude Code

The plugin imports the shared runtime from `${XDG_DATA_HOME:-~/.local/share}/model-effort-router/runtime`. Install a matching checkout with `python3 scripts/install_core.py`; for development set `MER_CORE_PATH="$PWD"`.

The UserPromptSubmit hook classifies eligible requests and recommends the role, model, and effort. It does not change Main's active model or execute work.

- `implementation`, `fix`, `lint`, and `test` use the execution lane (`claude-sonnet-5-5` by default); `plan`, `design`, `review`, and `analysis` use the reasoning lane (`claude-opus-5-5` by default).
- Effort is `low`, `medium`, `high`, `xhigh`, or `max`. Security-sensitive review/design requests may have a `high` minimum. Unsupported efforts return a routing error.
- Use `mer route --role <role> --effort <effort>` to select an explicit profile. Both values are required.
- `python3 ${CLAUDE_PLUGIN_ROOT}/bin/mer route --json '<task>'` prints a route. Classifier failures leave the host request unblocked; the CLI reports them as errors.

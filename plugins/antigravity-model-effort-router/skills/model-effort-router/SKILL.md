---
name: model-effort-router
description: Select a model and effort profile for software work in Antigravity. Use when the user asks for routing advice or provides a [model-effort-router] recommendation.
---

# Model-Effort Router (Antigravity)

The plugin imports the shared runtime from
`${XDG_DATA_HOME:-~/.local/share}/model-effort-router/runtime`. If it is
missing, install it from a matching repository checkout with
`python3 scripts/install_core.py`. For a checkout, use
`MER_CORE_PATH="$PWD"`.

For a new task, classify its difficulty and risk, then use the matching model and effort. The existing router core can produce a recommendation with `mer chat`; it does not intercept later prompts.

- Start an interactive Antigravity session at a routed profile with `python3 "$HOME/.gemini/antigravity-cli/plugins/model-effort-router/bin/mer" chat '<task>'` (CLI install). For an IDE workspace install, use `python3 .agents/plugins/model-effort-router/bin/mer chat '<task>'` from the workspace root.
- For a manual session, set `{"router":{"mode":"manual"}}` in `.model-effort-router.json`, then put a `/router session=balanced:medium` line first in the request.
- For an offline preview, use `mer chat --dry-run --level L1..L5 '<task>'`.
- Automatic classification through the subscription backend is unavailable because a read-only isolated classifier has not been verified. Use configured `nimble` (loopback Ollama) or `jev` if automatic routing is desired.
- `mer run`, escalation/resume, independent automated review, and plan/review-only chat are unavailable until execution isolation is verified. Do not use plan mode as a security boundary.
- The Test Gate alone is `python3 "$HOME/.gemini/antigravity-cli/plugins/model-effort-router/bin/mer-gate"` (CLI install).

Profiles map economy to Gemini 3.8 Flash, balanced to Claude Sonnet 5.5, and frontier to Claude Opus 5.5. The selected effort is encoded in Antigravity's model slug. Abstract `xhigh` maps to the available `high` effort.

---
name: model-effort-router
description: Classify the current coding request by difficulty from L1 to L5 and delegate it to a Claude Code agent whose model and effort match the selected level. Use before implementation when model and effort should be automatically selected from scope, ambiguity, diagnosis, design, risk, and verification complexity.
model: sonnet
effort: low
---

# Difficulty Router

Do not score `$ARGUMENTS` in the current session. Resolve the included router
relative to this file and run `python3 ../../scripts/router.py "$ARGUMENTS" --platform claude-code --format json`. Its fixed Terra preflight result is the
source of truth.

1. Announce: `Route: <level> · <model> · <effort>` from the JSON result.
2. Report when `source` is `fallback`.
3. Delegate the complete task to the plugin agent `model-effort-router:level-N-*` matching the selected level using the Agent tool.
4. Do not invoke this router again from the delegated agent.
5. Re-route only if new evidence materially raises scope or risk.

When no agent runtime is available, use the included launcher script to start a new process with the selected profile.

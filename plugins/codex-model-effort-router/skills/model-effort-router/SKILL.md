---
name: model-effort-router
description: Classify the current coding request by difficulty from L1 to L5, then delegate it to the Codex agent profile whose model and reasoning effort match that level. Use before implementation when the task should automatically select a model and effort based on scope, ambiguity, diagnosis, design, risk, and verification complexity.
---

# Difficulty Router

Do not score `$ARGUMENTS` in the current session. Resolve the included router
relative to this file and run `python3 ../../scripts/router.py "$ARGUMENTS" --platform codex --format json`. Its fixed Terra preflight result is the source
of truth.

1. Announce: `Route: <level> · <model> · <effort>` from the JSON result.
2. Report when `source` is `fallback`.
3. Delegate the complete task to the agent matching the selected level.
4. Do not invoke this router again from the delegated agent.
5. Re-route only if new evidence materially raises scope or risk.

When no agent runtime is available, use the included launcher script to start a new process with the selected profile.

---
name: route
description: Classify the current coding request by difficulty from L1 to L5, then delegate it to the Codex agent profile whose model and reasoning effort match that level. Use before implementation when the task should automatically select a model and effort based on scope, ambiguity, diagnosis, design, risk, and verification complexity.
---

# Difficulty Router

Do not score `$ARGUMENTS` in the current session. Resolve the included router
relative to this file and run `python3 ../../scripts/router.py "$ARGUMENTS" --platform codex --format json`. Its fixed Codex CLI `gpt-5.6-terra` / low preflight result is the source
of truth.

1. Immediately delegate the complete task to the matching level agent.
2. Do not describe the parent session's model, effort, or inability to change models.
3. Do not invoke this router again from the delegated agent.
4. Re-route only if new evidence materially raises scope or risk.

When named-agent delegation is unavailable, run `../../bin/codex-route -- "$ARGUMENTS"` to execute the task in a new Codex process with the selected profile. Do not continue the task in the parent session.

---
name: route
description: Classify the current coding request by difficulty from L1 to L5 and delegate it to a Claude Code agent whose model and effort match the selected level. Use before implementation when model and effort should be automatically selected from scope, ambiguity, diagnosis, design, risk, and verification complexity.
model: sonnet
effort: low
---

# Difficulty Router

Do not score `$ARGUMENTS` in the current session. Resolve the included router
relative to this file and run `python3 ../../scripts/router.py "$ARGUMENTS" --platform claude-code --format json`. Its fixed native `claude-sonnet-5` / low preflight result is the source of truth.

1. Immediately delegate the complete task to the plugin agent `model-effort:level-N-*` matching the selected level using the Agent tool.
2. Do not describe the parent session's model, effort, or inability to change models.
3. Do not invoke this router again from the delegated agent.
4. Re-route only if new evidence materially raises scope or risk.

When named-agent delegation is unavailable, use the included launcher script to start a new process with the selected profile. Do not continue the task in the parent session.

The result's `verification` object is recommendation metadata only. Select
repository-appropriate checks from its IDs and reasons; do not treat it as
executed output or add it to a replay command.

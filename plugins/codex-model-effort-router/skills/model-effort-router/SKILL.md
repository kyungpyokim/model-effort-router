---
name: model-effort-router
description: Classify the current coding request by difficulty from L1 to L5, then delegate it to the Codex agent profile whose model and reasoning effort match that level. Use before implementation when the task should automatically select a model and effort based on scope, ambiguity, diagnosis, design, risk, and verification complexity.
---

# Difficulty Router

Classify `$ARGUMENTS` or the current user task using `references/routing-policy.md`.

1. Score scope, ambiguity, diagnosis, design, risk, and verification from 0 to 2.
2. Sum the score and map it to L1-L5.
3. Apply hard floors.
4. Announce: `Route: <level> · <model> · <effort>`.
5. Delegate the complete task to the agent matching the selected level.
6. Do not invoke this router again from the delegated agent.
7. Re-route only if new evidence materially raises scope or risk.

When no agent runtime is available, use the included launcher script to start a new process with the selected profile.

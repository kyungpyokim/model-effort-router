---
name: route
description: Classify the current coding request by task_type and difficulty (L1-L5), then delegate it to the Codex agent profile whose model and reasoning effort match. Use before implementation when the task should automatically select a model and effort based on type, scope, ambiguity, diagnosis, design, risk, and verification complexity.
---

# Task-Type and Difficulty Router

Do not score `$ARGUMENTS` in the current session. Resolve the included router
relative to this file and run `python3 ../../scripts/router.py "$ARGUMENTS" --platform codex --format json`. Its fixed Codex CLI `gpt-5.6-terra` / low preflight result is the source
of truth.

1. Read the JSON result's `mode`.
2. For `single`, immediately delegate the complete task to the matching level
   agent with the model and effort from the selected matrix row.
3. For `two_stage` (`architectural_refactoring` L3+), run the printed stage
   commands in order: the planner writes the plan file, then the executor
   reads it together with the repository and implements it. Never run the
   executor after a failed plan stage.
4. Do not describe the parent session's model, effort, or inability to change models.
5. Do not invoke this router again from a delegated or executed agent.
6. Re-route only if new evidence materially raises scope or risk.

When named-agent delegation is unavailable, save that JSON result to a temporary file, then run `../../bin/codex-route --route-file <route.json>`. This replays the result's selected command without another classification; two-stage results remain success-dependent. Do not continue the task in the parent session.

The result's `verification` object is recommendation metadata only. The
selected executor receives recommended IDs and reasons, selects applicable
existing repository checks, and reports results or why a check was not run.
Do not treat it as executed output or add it to a replay command.

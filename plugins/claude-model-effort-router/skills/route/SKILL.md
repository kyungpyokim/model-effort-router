---
name: route
description: Classify the current coding request by difficulty from L1 to L5 and delegate it to a Claude Code agent whose model and effort match the selected task type and level. Use before implementation when model and effort should be automatically selected from scope, ambiguity, diagnosis, design, risk, and verification complexity.
model: sonnet
effort: low
---

# Difficulty Router

Do not score `$ARGUMENTS` in the current session. Resolve the included router
relative to this file and run `python3 ../../scripts/router.py "$ARGUMENTS" --platform claude-code --format json`. Its fixed native `claude-sonnet-5` / low preflight result is the source of truth. Save that JSON to a temporary file; it is the single classification for this request.

Model and effort are one profile: both come from the selected `task_type × level` matrix row, never from an agent default. The `review` and `design` rows resolve to `opus` at every level and `implementation` at L1 resolves to `haiku`, so a level-only delegation that keeps the agent's own model is wrong.

1. Execute the route by replaying its stored steps, not by re-deriving them: run `../../bin/claude-route --route-file <route.json>`. Pass the complete generated route JSON as that replay input and keep the original task with it. The launcher runs each stored `steps[].command` in order — a `single` route runs the `level-N` agent with the matrix `--model` and `--effort`; a `two_stage` route (`architectural_refactoring` L3+) runs the planner, then runs the executor only if the plan step succeeds — and never reclassifies. Do not continue the task in the parent session.
2. The executor that each step launches must use every `verification.recommended` ID and reason to select applicable existing repository checks and report each result or why it was not run.
3. Do not describe the parent session's model, effort, or inability to change models.
4. Do not invoke this router again from the replayed steps.
5. Re-route only if new evidence materially raises scope or risk.

When the launcher script cannot start a subprocess, delegate the complete task with the Agent tool to the plugin agent `model-effort:level-N-*` matching the selected level, and set the Agent tool `model` parameter to the route JSON `steps[0].model` so the matrix model overrides the agent default. The Agent tool cannot override effort, so take this path only when the `level-N` agent's frontmatter effort already equals `steps[0].effort`; otherwise wait for the launcher. A `two_stage` route cannot be expressed through the Agent tool and always needs the launcher.

The result's `verification` object is recommendation metadata only. The
selected executor receives recommended IDs and reasons, selects applicable
existing repository checks, and reports results or why a check was not run.
Do not treat it as executed output or add it to a replay command.

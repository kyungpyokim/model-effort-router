---
name: route
description: Classify a substantive coding task by task_type and difficulty (L1-L7 / Critical), then delegate it to the Codex agent profile whose model and reasoning effort match. Use before implementation, design, review, refactoring, or debugging work when model and effort should be selected from scope, ambiguity, diagnosis, design, risk, and verification complexity.
---

# Task-Type and Difficulty Router

Use this for a new substantive coding task. Do not route casual chat or status-only
questions. For a same-scope follow-up, reuse the complete stored route JSON. Create
a new route for a new review, a distinct task, or work that materially raises scope
or risk. If the stored route is unavailable after a resume or compaction, route again
instead of pretending it was reused.

Do not score `$ARGUMENTS` in the current session. Resolve the included router
relative to this file and run `python3 ../../scripts/router.py "$ARGUMENTS" --platform codex --format json`. Its cascading preflight result is the source
of truth.

1. Read the JSON result's `mode`.
2. For `single`, immediately delegate the complete task to the matching level
   agent with the model and effort from the selected matrix row. Pass the
   complete generated route JSON along with the original task. The delegated
   executor must use every `verification.recommended` ID and reason to select
   applicable existing repository checks and report each result or why it was
   not run.
3. For `two_stage` (`architectural_refactoring` L3+), run the printed stage
   commands in order: the planner writes the plan file, then the executor
   reads it together with the repository and implements it. Never run the
   executor after a failed plan stage.
4. Do not describe the parent session's model, effort, or inability to change models.
5. The classification-only process classifies only. An executor that received the
   complete route JSON executes its assigned work and does not invoke this router again.
6. Re-route only if new evidence materially raises scope or risk.

When named-agent delegation is unavailable, save that JSON result to a temporary file, then run `../../bin/codex-route --route-file <route.json>`. This replays the result's selected command without another classification; two-stage results remain success-dependent. Do not continue the task in the parent session.

Schema v3 `orchestration_eligible` is handoff metadata only. The local
`scripts/astra_adapter.py` is caller-invoked, revalidates worker inputs, and
preserves original verified artifacts; respect
`execution_strategy: direct` because direct v2 and v3 route-file replay never invokes it.

The result's `verification` object is recommendation metadata only. The
selected executor receives recommended IDs and reasons, selects applicable
existing repository checks, and reports results or why a check was not run.
Do not treat it as executed output or add it to a replay command.

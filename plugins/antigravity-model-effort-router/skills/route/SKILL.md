---
name: route
description: Classify a coding task by difficulty from L1 to L5 (plus an elevated/critical risk tier) and choose the closest available Antigravity model/effort variant. Use when the task should be routed by extracted task facts and fixed difficulty rules before execution.
---

# Model Effort Router

Do not classify the task in the current session. Resolve the included router
relative to this file and run `python3 ../../scripts/router.py "<task>" --platform antigravity --detect-antigravity-models --format json`. Save stdout unchanged to a fresh temporary `<route.json>` file. If an interactive session is requested, add `--interactive` when generating this JSON.

Execute the saved route with `../../bin/agy-route --route-file "<route.json>"`.
Pass the complete generated route JSON as the replay input and keep the original
task with it. The launcher executes `steps[].command` without reclassification
or model detection, preserving the selected matrix models and embedded effort.
A single route launches its L1-L5 agent; a two_stage route runs the
planner, then runs the executor only if the plan step succeeds. The executor must use every
`verification.recommended` ID and reason to select applicable existing
repository checks and report each result or why it was not run.

Do not describe the current session's model or attempt to change it. Do not
continue the task in the parent session or invoke the router again from replayed steps.

For bounded changes, use a single-agent fast path: applies only when the stored route has
`effective_level` L1-L3, empty `risk_flags`, no `security_review` or `migration_safety` in
`verification.recommended`, and a `single` `mode`. It means delegating
once to the routed executor (one step) with focused tests, at most one review, and no
multi-agent chains; re-route only if new evidence raises scope or risk. It never means the
parent implements the task itself.

Schema v7 is current. Schema v6 remains legacy and replay-compatible under the pre-v7 native permission grammar; it records facts, `risk_tier`, and `orchestration_eligible` as future metadata only.
`scripts/astra_adapter.py` is the unchanged orchestration adapter: caller-invoked, revalidates worker inputs, and
preserves original verified artifacts; respect
`execution_strategy: direct` because direct v2-v7 route-file replay never invokes it.

An `elevated` or `critical` `risk_tier` implies L5 and swaps the planning/judging stage to
`Claude Opus Thinking` (Antigravity has no effort setting); the implementer stage keeps its
matrix model. Reuse the stored route for same-task follow-ups; re-classify only on a
task-type change, large scope growth, new risk evidence, or a fact showing the approved
design cannot be implemented. Run one merged verification + review call after the
implementation steps and tests (not after each step), send it only the requirement,
approved plan, git diff, test results, and key code, and on review FAIL re-classify the
fix instead of having the reviewer fix it. An executor that finds something outside the
plan (scope expansion, architecture or public API change, DB migration, security boundary
change, plan/code mismatch) stops and returns evidence; difficulty or uncertainty alone
is not a reason.

The result's `verification` object is recommendation metadata only. The
selected executor receives recommended IDs and reasons, selects applicable
existing repository checks, and reports results or why a check was not run.
Do not treat it as executed output or add it to a replay command.

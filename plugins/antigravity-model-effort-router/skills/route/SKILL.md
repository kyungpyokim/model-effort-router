---
name: route
description: Classify a coding task by difficulty from L1 to L7 (or Critical Override) and choose the closest available Antigravity model/effort variant. Use when the task should be routed by scope, ambiguity, diagnosis, design, risk, and verification complexity before execution.
---

# Model Effort Router

Do not score the task in the current session. Resolve the included router
relative to this file and run `python3 ../../scripts/router.py "<task>" --platform antigravity --detect-antigravity-models --format json`. Save stdout unchanged to a fresh temporary `<route.json>` file. If an interactive session is requested, add `--interactive` when generating this JSON.

Execute the saved route with `../../bin/agy-route --route-file "<route.json>"`.
Pass the complete generated route JSON as the replay input and keep the original
task with it. The launcher executes `steps[].command` without reclassification
or model detection, preserving the selected matrix models and embedded effort.
A single route launches its L1-L7 or Critical agent; a two_stage route runs the
planner, then runs the executor only if the plan step succeeds. The executor must use every
`verification.recommended` ID and reason to select applicable existing
repository checks and report each result or why it was not run.

Do not describe the current session's model or attempt to change it. Do not
continue the task in the parent session or invoke the router again from replayed steps.

Schema v3 `orchestration_eligible` is future metadata only.
`scripts/astra_adapter.py` is caller-invoked, revalidates worker inputs, and
preserves original verified artifacts; respect
`execution_strategy: direct` because direct v2 and v3 route-file replay never invokes it.

The result's `verification` object is recommendation metadata only. The
selected executor receives recommended IDs and reasons, selects applicable
existing repository checks, and reports results or why a check was not run.
Do not treat it as executed output or add it to a replay command.

---
name: route
description: Classify a coding task by difficulty from L1 to L5 (plus an elevated/critical risk tier) and choose the closest available Antigravity model/effort variant. Use when the task should be routed by extracted task facts and fixed difficulty rules before execution.
---

# Model Effort Router

An L1 code change uses the regular workflow unless it is a gated `trivial_edit`.
`inspect` is read-only delegation. Reclassify when `INSPECT` becomes `MODIFY`;
scope preservation is required.

Before generating or replaying any code-change route, export its deterministic check:
`export MODEL_EFFORT_ROUTER_TEST_CMD='<command>'`. The same exported command must be
available before both route generation and route-file replay; the launcher refuses every
code-change route without it. `trivial_edit` skips only plan and review, never this check.

Do not classify the task in the current session. Resolve the included router
relative to this file and run `python3 ../../scripts/router.py "<task>" --platform antigravity --detect-antigravity-models --format json`. Save stdout unchanged to a fresh temporary `<route.json>` file. If an interactive session is requested, add `--interactive` when generating this JSON.

Execute the saved route with `../../bin/agy-route --route-file "<route.json>"`.
Pass the complete generated route JSON as the replay input and keep the original
task with it. The launcher executes `steps[].command` without reclassification
or model detection, preserving the selected matrix models and embedded effort.
The replay runs `scripts/pipeline.py`: a two_stage route runs the planner, then runs the executor only if the plan step succeeds; a code-change route (`pipeline` block present) then
runs the launcher's test gate (`MODEL_EFFORT_ROUTER_TEST_CMD`) and, unless it is `trivial_edit`, one merged review
with a bounded fix/re-plan loop. The executor must use every
`verification.recommended` ID and reason to select applicable existing
repository checks and report each result or why it was not run.

Do not describe the current session's model or attempt to change it. Do not
continue the task in the parent session or invoke the router again from replayed steps.

Workflow for code changes (`implementation`, `local_refactoring`, `architectural_refactoring`):
A gated `trivial_edit` stays single-stage with its deterministic test gate and no review. L1 code changes
use the regular workflow unless gated as `trivial_edit`. Other
code changes use the regular workflow with review at the appropriate level. The planner comes from the
platform's `design` row and a merged review runs after a green test run. Antigravity L2
routes stay single-stage (the design row equals the implementer, Flash High), but still get
the non-fast review; L3+ routes are two_stage (Pro High plans). Re-route only if new evidence raises
scope or risk. It never means the parent implements the task itself. `inspect` is read-only
delegation. Reclassify INSPECT to MODIFY when the task changes. Preserve the approved scope;
if `trivial_edit` needs broader work or its deterministic check cannot be run, stop and
reclassify when new evidence materially raises scope or risk.

Schema v7 records facts, `risk_tier`, and `orchestration_eligible` as future metadata only.
`scripts/astra_adapter.py` is the unchanged orchestration adapter: caller-invoked, revalidates worker inputs, and
preserves original verified artifacts; respect
`execution_strategy: direct` because direct v2-v7 route-file replay never invokes it.

An `elevated` or `critical` `risk_tier` implies L5 and swaps the planning and review stages to
`Claude Opus Thinking` (Antigravity has no effort setting); the implementer stage keeps its
matrix model. Reuse the stored route for same-task follow-ups; re-classify only on a
task-type change, large scope growth, new risk evidence, or a fact showing the approved
design cannot be implemented. Run one merged verification + review call after the
implementation steps and tests (not after each step), send it only the requirement,
approved plan, git diff, test results, and key code, and on review FAIL the reviewer does not
fix it: the route's implementer does. Planned (not enforced yet): choosing the fix model by fix
difficulty; today every fix uses the route's implementer. An executor that finds something outside the
plan (scope expansion, architecture or public API change, DB migration, security boundary
change, plan/code mismatch) stops and returns evidence; difficulty or uncertainty alone
is not a reason.

The result's `verification` object is recommendation metadata only. The
selected executor receives recommended IDs and reasons, selects applicable
existing repository checks, and reports results or why a check was not run.
Do not treat it as executed output or add it to a replay command.

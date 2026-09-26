---
name: route
description: Classify the current coding request by difficulty from L1 to L5 (plus an elevated/critical risk tier) and delegate it to a Claude Code agent whose model and effort match the selected task type and level. Use before implementation when model and effort should be automatically selected from extracted task facts and fixed difficulty rules.
model: haiku
effort: low
---

# Difficulty Router

An L1 code change uses the regular workflow unless it is a gated `trivial_edit`.
`inspect` is read-only delegation. Reclassify when `INSPECT` becomes `MODIFY`;
scope preservation is required.

Before generating or replaying any code-change route, export its deterministic check:
`export MODEL_EFFORT_ROUTER_TEST_CMD='<command>'`. The same exported command must be
available before both route generation and route-file replay; the launcher refuses every
code-change route without it. `trivial_edit` skips only plan and review, never this check.

Do not classify `$ARGUMENTS` in the current session. Do not change directory: the
router, the assessor, and the executor must run in the user's current working directory,
which is the repository the task refers to. `<router>` below is
`python3 "${CLAUDE_SKILL_DIR}/../../scripts/router.py"`. Do not write the assessor reply to a temp file.

Classify with the in-session assessor, not a nested CLI:

1. Run `<router> --print-classifier-prompt --repo-aware "$ARGUMENTS"` and call the Agent tool
   with `subagent_type` `model-effort:difficulty-assessor`, `model` `haiku`, and that output
   unchanged as the prompt. The assessor answers facts only; the router's difficulty rules
   pick the level.
   If the assessor's reply is truncated (cut off before a complete JSON object — it ran out of
   its tool-call budget), resume that same assessor call once via SendMessage asking it to
   finish emitting the JSON now instead of restarting; only fall back to step 4's from-scratch
   retry if the resumed reply is still not valid JSON.
2. Pass the assessor's JSON reply unchanged on stdin and read the route JSON from stdout:

   ```bash
   <router> "$ARGUMENTS" --platform claude-code --format json --classification-file - <<'FACTS_JSON'
   <assessor reply>
   FACTS_JSON
   ```
3. If the router exits `3`, the route JSON lists `unresolved_facts` and `questions`: facts the task
   and the assessor's repository reads could not settle. `unknown` is missing information, not
   risk, so never call a stronger model or reclassify to settle it, and never treat it as `yes`.
   Ask the user each question in `questions[]` (the `question` text, with its `options`), then
   rerun step 2 with the same assessor reply and one `--answer FACT=VALUE` per answer. An answer
   only fills a fact that is still unknown. If the user cannot answer, stop and report which
   information is missing; do not delegate the route.
   If the same exit `3` route JSON reports `ambiguity: "ambiguous"`, the request itself is
   under-specified (it names neither an operation nor a concrete target): ask the user to restate
   it with what to change and where. Never answer that with `--answer`, and never reclassify it.
4. If the router exits with any other non-zero code, the assessor reply was not valid JSON. Call the assessor
   once more; if the router still exits non-zero, do not guess a route and do not delegate.
   Report the failure, ask the user for `task_type` and `level`, and rerun the router with
   `--task-type` and `--level`.
5. Outside that manual step, never run the router in this flow without `--classification-file`:
   that spawns a nested classifier CLI. Never delegate a route whose `source` is `fallback`;
   classification did not happen, so stop and report it.

The model comes from the selected `task_type × level` matrix row plus any configured L2 refinement (already applied in `steps[].model`), never from an agent default. `review` and `design` use `claude-haiku-4-5` at L1, then `claude-opus-5-5` at L2-L5. The `elevated` and `critical` `risk_tier` values imply L5 and raise only the planning and review stages' effort (Opus xhigh / max); the implementer keeps its matrix profile. A level-only delegation that keeps the agent's own model is wrong.

1. Pick the executor from the route JSON's `pipeline` block. Never reclassify, and do not continue or implement the task in the parent session.
   - `pipeline` non-null (every code change: `implementation`, `local_refactoring`, `architectural_refactoring`): save the complete route JSON, exactly as generated, to a fresh temp file (`mktemp`), then run it with Bash from the user's current working directory:

     ```bash
     python3 "${CLAUDE_SKILL_DIR}/../../scripts/pipeline.py" --route-file <route.json> --cleanup-plan-dir
     ```

     Run it in the background: it can outlast a foreground Bash timeout. The launcher runs the plan, implement, test, review, and fix stages itself (see Pipeline guidance below), so do not run those steps with the Agent tool. Report to the user the exit code (`0` done; `2` invalid route file; `10` gave up after the fix and re-plan budget; `11` review gave no verdict; `12` a stage failed to start; `13` no plan file; any other code is the stage's own exit code) and the last `phase=` line of stderr (or `state.json` in the work directory). The user's deterministic check goes in `MODEL_EFFORT_ROUTER_TEST_CMD` (or `--test-cmd`); ask the user once if you do not know it, and if there is none stop and ask for one: the launcher refuses code-change routes without it.
   - `pipeline` null (read-only `design` / `review`): run the Agent tool, one call per stored step, in order. Pass the complete generated route JSON with the original task. For each step, set `subagent_type` to `steps[].agent.subagent_type`, `model` to `steps[].agent.model`, and use the last element of `steps[].command` as the prompt; it already carries the task, the stage instructions, and the verification handoff. These routes are `single`, so it is one call.
2. The Agent tool cannot set effort, so `steps[].agent.subagent_type` is an `effort-*` agent whose frontmatter pins `steps[].effort`. Do not substitute a `level-N` agent.
3. The executor must use every `verification.recommended` ID and reason to select applicable existing repository checks and report each result or why it was not run.
4. Do not invoke this router again from the delegated steps.
5. Re-route only if new evidence materially raises scope or risk. Reuse the stored route for same-task follow-ups.
6. `two_stage` code-change routes (a judge plans, a cheaper model implements) cover non-fast code changes except where the design row equals the implementer row. Every other route is `single`: one step, no chain (a gated `trivial_edit`, or a read-only `design` / `review` route). L1 code changes use the regular workflow unless gated as `trivial_edit`. A `single` code-change route still goes through `pipeline.py`, so it gets the deterministic test gate (and, unless it is `trivial_edit`, the merged review); it never means the parent implements the task itself. `inspect` is read-only delegation. Preserve the approved scope; if `trivial_edit` needs broader work or its deterministic check cannot be run, stop and reclassify. Reclassify INSPECT to MODIFY when the task changes, or when new evidence materially raises scope or risk.

Outside a Claude Code session, run `bin/claude-route -- "<task>"` from a terminal. It classifies and then runs the same `pipeline.py` launcher; `--route-file` replays a stored route without reclassifying. `--interactive` is limited to read-only routes and gated `trivial_edit` routes; the latter still runs its deterministic test. `--print` is accepted and changes nothing.

Schema v7 records facts, `risk_tier`, and `orchestration_eligible` (future metadata only).
`scripts/astra_adapter.py` is the unchanged orchestration adapter: caller-invoked, revalidates worker inputs, and
preserves original verified artifacts; respect
`execution_strategy: direct` because direct v2-v7 route-file replay never invokes it.

Pipeline guidance (Opus thinks and verifies, Haiku and Sonnet implement). `pipeline.py` enforces:

- Follow-up questions in the same task reuse the stored route; do not route again.
  Re-classify only when the task type changes (for example inspect to modify), the scope
  grows a lot, new risk evidence appears, or a fact shows the approved design cannot be
  implemented.
- Every non-fast code change gets plan and review roles from the judge rows at `max(level, L2)`.
  The planner writes a plan file unless it equals the implementer; no required plan file stops the run (exit `13`).
- Tests run in the launcher without a model, and only a failure sends a truncated log to
  the cheap implementer to fix. Then ONE merged Opus verification and code review runs
  (read-only), given the requirement, plan, git diff, test results, and key code. Its effort is
  High by default, XHigh for an `elevated` `risk_tier`, and Max for `critical`.
- On review FAIL the reviewer does not fix it. The implementer fixes once, then the planning
  model re-plans. The limits come from `pipeline.limits` (`PIPELINE_LIMITS` in `router.py`): at
  most 2 test fixes per cycle (the count resets after a re-plan), 1 review fix before a re-plan, and 1 re-plan; beyond that the run gives up
  (exit `10`).
- An executor that finds something outside the plan stops with an `ESCALATE:` line and evidence,
  which triggers the re-plan instead of the executor deciding structure itself. Valid evidence:
  scope expansion, architecture change, public API change, DB migration, security boundary
  change, or a plan/code-structure mismatch. "It is hard" or "I am unsure" alone is not a reason
  to escalate.
- Planned (Phase 3), not enforced yet: choosing the fix model by fix difficulty after a review
  FAIL (simple to Haiku, ordinary logic to Sonnet, design problem to Opus). Today every fix uses
  the route's implementer.

The result's `verification` object is recommendation metadata only. The
selected executor receives recommended IDs and reasons, selects applicable
existing repository checks, and reports results or why a check was not run.
Do not treat it as executed output or add it to a replay command.

---
name: route
description: Classify a substantive coding task by task_type and difficulty (L1-L5 plus an elevated/critical risk tier), then delegate it to the Codex agent profile whose model and reasoning effort match. Use before implementation, design, review, refactoring, or debugging work when model and effort should be selected from extracted task facts and fixed difficulty rules.
---

# Task-Type and Difficulty Router

Use this for a new substantive coding task. Do not route casual chat or status-only
questions. For a same-scope follow-up, reuse the complete stored route JSON. Create
a new route for a new review, a distinct task, or work that materially raises scope
or risk. If the stored route is unavailable after a resume or compaction, route again
instead of pretending it was reused.

Do not score `$ARGUMENTS` in the current session. Resolve the included router
relative to this file as `<router>` = `<skill-dir>/../../scripts/router.py` and run it
from the user's current working directory. The router never spawns a nested `codex exec`
in this flow, because that classifier cannot start inside the workspace sandbox; a spawned
worker classifies instead.

1. Run `python3 <router> --print-classifier-prompt --repo-aware "$ARGUMENTS"` and spawn a
   read-only worker with `model` and `reasoning_effort` set to `gpt-5.6-luna` and `medium`,
   passing that output unchanged as its only message. The worker answers facts only; the
   router's difficulty rules pick the level. Do not write the reply to a temp file.
2. Pass the worker's JSON reply unchanged on stdin and read the route JSON from stdout:

   ```bash
   python3 <router> "$ARGUMENTS" --platform codex --format json --classification-file - <<'FACTS_JSON'
   <worker reply>
   FACTS_JSON
   ```
3. If the router exits `3`, the route JSON lists `unresolved_facts` and `questions`: facts the task
   and the worker's repository reads could not settle. `unknown` is missing information, not risk,
   so never classify again with a stronger model to settle it, and never treat it as `yes`. Ask the
   user each question in `questions[]` (the `question` text, with its `options`), then rerun step 2
   with the same worker reply and one `--answer FACT=VALUE` per answer. An answer only fills a fact
   that is still unknown. If the user cannot answer, stop and report which information is missing;
   do not delegate the route.
   If the router exits with any other non-zero code, the classification JSON was invalid. Classify once more; if it
   still fails, do not guess a route and do not delegate. Report the failure, ask the user for
   `task_type` and `level`, and rerun step 2 with `--task-type` and `--level`.
   Never run the router in this flow without `--classification-file`:
   that spawns a nested `codex exec` that fails in the sandbox. Never delegate a route whose
   `source` is `fallback`; classification did not happen, so stop and report it.
4. Pick the executor from the route JSON's `pipeline` block. Never reclassify, and do not continue or implement the task in the parent session.
   - `pipeline` non-null (every code change: `implementation`, `local_refactoring`, `architectural_refactoring`): save the complete route JSON, exactly as generated, to a fresh temp file, then run `<skill-dir>/../../bin/codex-route --route-file <route.json>` from the user's current working directory (it runs `scripts/pipeline.py`). Run it in the background: it can outlast a foreground shell timeout. The launcher runs the plan, implement, test, review, and fix stages itself (see Pipeline guidance below), so do not spawn workers for them. Report to the user the exit code (`0` done; `2` invalid route file; `10` gave up after the fix and re-plan budget; `11` review gave no verdict; `12` a stage failed to start; `13` no plan file) and the last `phase=` line of stderr (or `state.json` in the work directory). The user's deterministic check goes in `MODEL_EFFORT_ROUTER_TEST_CMD`; ask the user once if you do not know it, and if there is none leave it unset: the review prompt then states that no test command was configured.
   - `pipeline` null (read-only `design` / `review`): delegate each entry in `steps` in order to a spawned worker whose `model` and `reasoning_effort` are set to that step's `model` and `effort`; never inherit the parent session model. The worker message is the `developer_instructions` value from that step's `command`, followed by the last element of `command`. Pass the complete generated route JSON along with the original task. The delegated executor must use every `verification.recommended` ID and reason to select applicable existing repository checks and report each result or why it was not run.
5. `two_stage` code-change routes (a judge plans, a cheaper model implements) cover L2+ code changes except where the design row equals the implementer row (`architectural_refactoring` at L2); the launcher runs the planner, which writes the plan file, then the executor, which reads it with the repository. Never run the executor after a failed plan stage.
6. Do not describe the parent session's model, effort, or inability to change models.
7. The classification-only worker classifies only. An executor that received the
   complete route JSON executes its assigned work and does not invoke this router again.
8. Re-route only if new evidence materially raises scope or risk; same-task follow-ups reuse the stored route.
9. Every route that is not `two_stage` is `single`: one step, no chain (an L1 code change, or a read-only `design` / `review` route). A `single` code-change route still goes through `codex-route` / `pipeline.py`, so it gets the test gate (and, at L2+, the merged review); it never means the parent implements the task itself. Re-route only if new evidence raises scope or risk.

Schema v6 records facts, `risk_tier`, and `orchestration_eligible` as handoff metadata only. The local
`scripts/astra_adapter.py` is the unchanged orchestration adapter: caller-invoked, revalidates worker inputs, and
preserves original verified artifacts; respect
`execution_strategy: direct` because direct v2-v6 route-file replay never invokes it.

Pipeline guidance (Sol thinks and verifies, Luna and Terra implement). `pipeline.py` enforces:

- Follow-up questions in the same task reuse the stored route; do not route again.
  Re-classify only when the task type changes (for example inspect to modify), the scope
  grows a lot, new risk evidence appears, or a fact shows the approved design cannot be
  implemented.
- The planner (Sol) writes a plan file, then the implementer (Luna/Terra) implements it. No
  plan file stops the run (exit `13`).
- Tests run in the launcher without a model, and only a failure sends a truncated log to
  the cheap implementer to fix. Then ONE merged Sol verification and code review runs, given
  the requirement, plan, git diff, test results, and key code. Its effort is High by default,
  XHigh for an `elevated` `risk_tier`, and Max for `critical`. Below L2 there is no review, only
  the test gate and the fix loop.
- On review FAIL the reviewer does not fix it. The implementer fixes once, then the planning
  model re-plans. The limits come from `pipeline.limits` (`PIPELINE_LIMITS` in `router.py`): at
  most 2 test fixes, 1 review fix before a re-plan, and 1 re-plan; beyond that the run gives up
  (exit `10`).
- An executor that finds something outside the plan stops with an `ESCALATE:` line and evidence,
  which triggers the re-plan instead of the executor deciding structure itself. Valid evidence:
  scope expansion, architecture change, public API change, DB migration, security boundary
  change, or a plan/code-structure mismatch. "It is hard" or "I am unsure" alone is not a reason
  to escalate.
- Planned (Phase 3), not enforced yet: choosing the fix model by fix difficulty after a review
  FAIL (simple to Luna medium, ordinary logic to Terra, design problem to Sol). Today every fix
  uses the route's implementer.

The result's `verification` object is recommendation metadata only. The
selected executor receives recommended IDs and reasons, selects applicable
existing repository checks, and reports results or why a check was not run.
Do not treat it as executed output or add it to a replay command.

---
name: route
description: Classify the current coding request by difficulty from L1 to L5 (plus an elevated/critical risk tier) and delegate it to a Claude Code agent whose model and effort match the selected task type and level. Use before implementation when model and effort should be automatically selected from extracted task facts and fixed difficulty rules.
model: sonnet
effort: low
---

# Difficulty Router

Do not classify `$ARGUMENTS` in the current session. Do not change directory: the
router, the assessor, and the executor must run in the user's current working directory,
which is the repository the task refers to. `<router>` below is
`python3 "${CLAUDE_SKILL_DIR}/../../scripts/router.py"`. Do not write the assessor reply to a temp file.

Classify with the in-session assessor, not a nested CLI:

1. Run `<router> --print-classifier-prompt --repo-aware "$ARGUMENTS"` and call the Agent tool
   with `subagent_type` `model-effort:difficulty-assessor`, `model` `sonnet`, and that output
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
4. If the router exits with any other non-zero code, the assessor reply was not valid JSON. Call the assessor
   once more; if the router still exits non-zero, do not guess a route and do not delegate.
   Report the failure, ask the user for `task_type` and `level`, and rerun the router with
   `--task-type` and `--level`.
5. Outside that manual step, never run the router in this flow without `--classification-file`:
   that spawns a nested classifier CLI. Never delegate a route whose `source` is `fallback`;
   classification did not happen, so stop and report it.

The model comes from the selected `task_type × level` matrix row plus any configured L2 refinement (already applied in `steps[].model`), never from an agent default. `review` and `design` use `claude-haiku-4-5` at L1, then `claude-opus-5` at L2-L5. The `elevated` and `critical` `risk_tier` values imply L5 and raise only the planning/judging stage effort (Opus xhigh / max); the implementer keeps its matrix profile. A level-only delegation that keeps the agent's own model is wrong.

1. For a `single` route, execute its one stored step with the Agent tool. Pass the complete generated route JSON with the original task, set `subagent_type` to `steps[].agent.subagent_type`, `model` to `steps[].agent.model`, and use the last element of `steps[].command` as the prompt; it already carries the task, the stage instructions, and the verification handoff. Never reclassify, and do not continue the task in the parent session.
2. The Agent tool cannot set effort, so `steps[].agent.subagent_type` is an `effort-*` agent whose frontmatter pins `steps[].effort`. Do not substitute a `level-N` agent.
3. The delegated agent must use every `verification.recommended` ID and reason to select applicable existing repository checks and report each result or why it was not run.
4. Do not invoke this router again from the delegated steps.
5. Re-route only if new evidence materially raises scope or risk. Reuse the stored route for same-task follow-ups.
6. For bounded changes, use a single-agent fast path: applies only when the stored route has
   `effective_level` L1-L3, empty `risk_flags`, no `security_review` or `migration_safety` in
   `verification.recommended`, and a `single` `mode`. It means delegating
   once to the routed executor (one step) with focused tests, at most one review, and no
   multi-agent chains; re-route only if new evidence raises scope or risk. It never means the
   parent implements the task itself.

For a `two_stage` route (`architectural_refactoring` L3+, or `implementation` / `local_refactoring` at L5), do not call the planner or executor directly with Agent. Save the complete route JSON and run `bin/claude-route --route-file <route.json>` from the same working directory. The parent pipeline captures planner stdout, validates it, atomically writes the shared `plan.json`, and preserves the generated read/edit stage permissions before it runs the executor. Never run the executor after a failed plan stage.

Outside a Claude Code session, run `bin/claude-route -- "<task>"` from a terminal. It
starts an interactive `claude` session with the matrix `--model` and `--effort`, so the
executor keeps normal edit permissions; `--route-file` replays stored `steps[].command`
without reclassifying. Generated implement/fix commands use `acceptEdits`; generated
plan/review commands deny file edits, including non-interactive `-p` runs.

Schema v7 is current. Schema v6 remains legacy and replay-compatible under the pre-v7 native permission grammar. Schema v7 records facts, `risk_tier`, and `orchestration_eligible` (future metadata only).
`scripts/astra_adapter.py` is the unchanged orchestration adapter: caller-invoked, revalidates worker inputs, and
preserves original verified artifacts; respect
`execution_strategy: direct` because direct v2-v7 route-file replay never invokes it.

Pipeline guidance (Opus thinks and verifies, Haiku and Sonnet implement):

- Follow-up questions in the same task reuse the stored route; do not route again.
  Re-classify only when the task type changes (for example inspect to modify), the scope
  grows a lot, new risk evidence appears, or a fact shows the approved design cannot be
  implemented.
- Do not call Opus after each step. Batch the implementation steps and run the tests
  (test execution stays on the cheap implementation models), then make ONE Opus call
  that merges verification and code review. Send only the original requirement, the
  approved plan, the git diff, the test results, and the key code, never the whole
  session. Effort is High by default, XHigh for an `elevated` `risk_tier`, and Max for
  `critical`.
- On review FAIL the reviewer does not fix it. Re-classify the fix: simple (for example
  null handling) to Haiku, an ordinary logic change to Sonnet, a design problem to Opus,
  then a final Opus review.
- An executor that finds something outside the plan stops and returns evidence for an
  Opus re-plan instead of deciding structure itself. Valid evidence: scope expansion,
  architecture change, public API change, DB migration, security boundary change, or a
  plan/code-structure mismatch. "It is hard" or "I am unsure" alone is not a reason to
  escalate.


The result's `verification` object is recommendation metadata only. The
selected executor receives recommended IDs and reasons, selects applicable
existing repository checks, and reports results or why a check was not run.
Do not treat it as executed output or add it to a replay command.

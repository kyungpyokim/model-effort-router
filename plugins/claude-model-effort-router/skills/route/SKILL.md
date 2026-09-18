---
name: route
description: Classify the current coding request by difficulty from L1 to L7 (or Critical Override) and delegate it to a Claude Code agent whose model and effort match the selected task type and level. Use before implementation when model and effort should be automatically selected from extracted task facts and fixed difficulty rules.
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
3. If the route JSON has `needs_context: true`, call the assessor once more with the same
   prompt and `model` `opus`, then rerun step 2 with this JSON envelope on stdin. Both calls
   read the same repository-aware prompt with the same agent; escalation instead uses a
   stronger model to correct the primary's answer. It combines the primary and escalated
   facts before routing: a primary irreversible, security/payment, persisted-data,
   public-API, trust-boundary, or silent-failure "yes" is always kept (sticky), while
   `security_domain`, `reviews_security_sensitive_code`, and `blast_radius` are correctable
   and may be lowered once the escalated reply gives an explicit, non-`unknown` answer.

   ```json
   {"primary": <first classifier reply>, "escalated": <repository-aware classifier reply>}
   ```

   Escalate at most once. If that call fails, keep the first route.
4. If the router exits non-zero, the assessor reply was not valid JSON. Call the assessor
   once more; if the router still exits non-zero, do not guess a route and do not delegate.
   Report the failure, ask the user for `task_type` and `level`, and rerun the router with
   `--task-type` and `--level`.
5. Outside that manual step, never run the router in this flow without `--classification-file`:
   that spawns a nested classifier CLI. Never delegate a route whose `source` is `fallback`;
   classification did not happen, so stop and report it.

The model comes from the selected `task_type × level` matrix row, never from an agent default. `review` and `design` use `claude-haiku-4-5` at L1, `claude-opus-5` at L2-L4, then `claude-fable-5-1` with Opus fallback at L5-L7. A level-only delegation that keeps the agent's own model is wrong.

1. Execute the route with the Agent tool, one call per stored step, in order. Pass the complete generated route JSON with the original task. For each step, set `subagent_type` to `steps[].agent.subagent_type`, `model` to `steps[].agent.model`, and use the last element of `steps[].command` as the prompt; it already carries the task, the stage instructions, and the verification handoff. A `single` route is one call; a `two_stage` route (`architectural_refactoring` L3+) runs the planner, then runs the executor only if the plan step succeeds. Never reclassify, and do not continue the task in the parent session.
2. The Agent tool cannot set effort, so `steps[].agent.subagent_type` is an `effort-*` agent whose frontmatter pins `steps[].effort`. Do not substitute a `level-N` agent.
3. The delegated agent must use every `verification.recommended` ID and reason to select applicable existing repository checks and report each result or why it was not run.
4. Do not invoke this router again from the delegated steps.
5. Re-route only if new evidence materially raises scope or risk.

Outside a Claude Code session, run `bin/claude-route -- "<task>"` from a terminal. It
starts an interactive `claude` session with the matrix `--model` and `--effort`, so the
executor keeps normal edit permissions; `--route-file` replays stored `steps[].command`
without reclassifying. A non-interactive `-p` executor runs with default permissions and
cannot edit files unless the user's settings allow it.

Schema v4 records facts and `orchestration_eligible` as future metadata only.
`scripts/astra_adapter.py` is caller-invoked, revalidates worker inputs, and
preserves original verified artifacts; respect
`execution_strategy: direct` because direct v2-v4 route-file replay never invokes it.

The result's `verification` object is recommendation metadata only. The
selected executor receives recommended IDs and reasons, selects applicable
existing repository checks, and reports results or why a check was not run.
Do not treat it as executed output or add it to a replay command.

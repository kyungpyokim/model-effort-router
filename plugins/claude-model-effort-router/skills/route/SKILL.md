---
name: route
description: Classify the current coding request by difficulty from L1 to L7 (or Critical Override) and delegate it to a Claude Code agent whose model and effort match the selected task type and level. Use before implementation when model and effort should be automatically selected from scope, ambiguity, diagnosis, design, risk, and verification complexity.
model: sonnet
effort: low
---

# Difficulty Router

Do not score `$ARGUMENTS` in the current session. Do not change directory: the
router and the executor must run in the user's current working directory, which is
the repository the task refers to. Run
`python3 "${CLAUDE_SKILL_DIR}/../../scripts/router.py" "$ARGUMENTS" --platform claude-code --format json > <route.json>`.
Its cascading native preflight (`claude-haiku-4-5`, escalating to `claude-sonnet-5`) is the source of truth. The saved JSON is the single classification for this request.

If the router exits non-zero, its `source` is `fallback`: the preflight failed and
the L3 route is a guess. Do not delegate it. Report the failure, ask the user for
`task_type` and `level`, and rerun the router with `--task-type` and `--level`.

The model comes from the selected `task_type × level` matrix row, never from an agent default. The `review` and `design` rows resolve to `opus` at every level and `implementation` at L1 resolves to `haiku`, so a level-only delegation that keeps the agent's own model is wrong.

1. Execute the route with the Agent tool, one call per stored step, in order. Pass the complete generated route JSON with the original task. For each step, set `subagent_type` to `steps[].agent.subagent_type`, `model` to `steps[].agent.model`, and use the last element of `steps[].command` as the prompt; it already carries the task, the stage instructions, and the verification handoff. A `single` route is one call; a `two_stage` route (`architectural_refactoring` L3+) runs the planner, then runs the executor only if the plan step succeeds. Never reclassify, and do not continue the task in the parent session.
2. The Agent tool cannot set effort: the agent's frontmatter effort applies. When it differs from `steps[].effort`, state both values instead of claiming the matrix effort.
3. The delegated agent must use every `verification.recommended` ID and reason to select applicable existing repository checks and report each result or why it was not run.
4. Do not invoke this router again from the delegated steps.
5. Re-route only if new evidence materially raises scope or risk.

Outside a Claude Code session, run `bin/claude-route -- "<task>"` from a terminal. It
starts an interactive `claude` session with the matrix `--model` and `--effort`, so the
executor keeps normal edit permissions; `--route-file` replays stored `steps[].command`
without reclassifying. A non-interactive `-p` executor runs with default permissions and
cannot edit files unless the user's settings allow it.

Schema v3 `orchestration_eligible` is future metadata only.
`scripts/astra_adapter.py` is caller-invoked, revalidates worker inputs, and
preserves original verified artifacts; respect
`execution_strategy: direct` because direct v2 and v3 route-file replay never invokes it.

The result's `verification` object is recommendation metadata only. The
selected executor receives recommended IDs and reasons, selects applicable
existing repository checks, and reports results or why a check was not run.
Do not treat it as executed output or add it to a replay command.

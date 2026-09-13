---
name: route
description: Classify a substantive coding task by task_type and difficulty (L1-L7 / Critical), then delegate it to the Codex agent profile whose model and reasoning effort match. Use before implementation, design, review, refactoring, or debugging work when model and effort should be selected from extracted task facts and fixed difficulty rules.
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
3. If the route JSON has `needs_context: true`, classify once more with `gpt-5.6-terra` /
   `medium` and the same prompt, and rerun step 2 with that reply alone; its facts replace the
   first reply's. Escalate at most once. If the second worker fails, keep the first route.
   If the router exits non-zero, the classification JSON was invalid. Classify once more; if it
   still fails, do not guess a route and do not delegate. Report the failure, ask the user for
   `task_type` and `level`, and rerun step 2 with `--task-type` and `--level`.
   Outside that manual step, never run the router in this flow without `--classification-file`:
   that spawns a nested `codex exec` that fails in the sandbox. Never delegate a route whose
   `source` is `fallback`; classification did not happen, so stop and report it.
4. Delegate each entry in `steps` in order to a spawned worker whose `model` and
   `reasoning_effort` are set to that step's `model` and `effort`; never inherit the parent
   session model. The worker message is the `developer_instructions` value from that
   step's `command`, followed by the last element of `command`. Pass the complete generated
   route JSON along with the original task. The delegated executor must use every
   `verification.recommended` ID and reason to select applicable existing repository
   checks and report each result or why it was not run.
5. For `two_stage` (`architectural_refactoring` L3+), the planner step writes the plan
   file, then the executor step reads it together with the repository and implements it.
   Never run the executor after a failed plan stage.
6. Do not describe the parent session's model, effort, or inability to change models.
7. The classification-only worker classifies only. An executor that received the
   complete route JSON executes its assigned work and does not invoke this router again.
8. Re-route only if new evidence materially raises scope or risk.

When named-agent delegation is unavailable, save that JSON result to a temporary file, then run `<skill-dir>/../../bin/codex-route --route-file <route.json>` from the same working directory. This replays the result's selected command without another classification; two-stage results remain success-dependent. Do not continue the task in the parent session.

Schema v3 `orchestration_eligible` is handoff metadata only. The local
`scripts/astra_adapter.py` is caller-invoked, revalidates worker inputs, and
preserves original verified artifacts; respect
`execution_strategy: direct` because direct v2 and v3 route-file replay never invokes it.

The result's `verification` object is recommendation metadata only. The
selected executor receives recommended IDs and reasons, selects applicable
existing repository checks, and reports results or why a check was not run.
Do not treat it as executed output or add it to a replay command.

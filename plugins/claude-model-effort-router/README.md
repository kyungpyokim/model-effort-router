# Claude Code Model Effort Router

## Install from the bundle marketplace

From Claude Code:

```text
/plugin marketplace add /absolute/path/to/model-effort-router
/plugin install model-effort@model-effort-router-bundle
/reload-plugins
```

## Route-first policy hook

Claude Code loads the plugin's `hooks/hooks.json` automatically. Its SessionStart
handler injects a short route-first policy telling the session to invoke
`model-effort:route` before substantive coding work; it does not classify a task,
start a worker, or block a prompt. The hook improves compliance but cannot force a
skill call, and stronger instructions from other plugins can still win. Invoke
`/model-effort:route <task>` directly when routing must happen.

## Test without installation

```bash
claude --plugin-dir .
```

Then invoke:

```text
/model-effort:route <task>
```

The router preflights each task with native `claude-sonnet-5` (no effort parameter); facts that stay unknown get
one bounded same-model lookup, then a question to the user (exit `3`), never a stronger model. Claude's JSON-schema output is
read from its `structured_output` result field. Safe mode,
no tools, plan permissions, no session persistence, and a temporary working
directory isolate the classifier. Failure safely selects L3. Each agent pins
`model` and `effort` in frontmatter.

The v5 execution matrix (levels L1-L5, plus a separate risk tier) is:

| task type | L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|
| implementation / local_refactoring | haiku | opus high -> haiku | opus high -> sonnet med | opus high -> sonnet high | opus high -> sonnet high |
| design / review | haiku | opus high | opus high | opus high | opus high |
| architectural_refactoring | haiku | opus high | opus high -> sonnet med | opus xhigh -> sonnet high | opus xhigh -> sonnet high |

`A -> B` is the success-dependent planner-to-implementer chain. Every non-fast code change
(`implementation`, `local_refactoring`, `architectural_refactoring`) gets its planner from the
`design` row and a merged review from the `review` row; the exception is `architectural_refactoring`
at L2, where the design row (opus high) equals the implementer, so no planner is inserted and
the route stays single-stage. There the review judge is the same model as the implementer, so the review is a self-review until reviewer separation lands (Phase 3). A gated `trivial_edit` is single-stage with its deterministic test gate; otherwise L1 uses the regular workflow. At L2, `requires_code_understanding` = yes swaps the
`haiku` implementer for `sonnet low`.
Read-only design and review use `files_touched: 0`; files only read for context do not
count. For work that changes files, the bucket (`1`, `2-5`, `6+`) is answered only from
evidence - a stated count, a named file or module list, an attached diff, or what the
repository-aware reads show - never from the described scope, size, or complexity, and no
scope signal is `unknown`. The `elevated` and `critical` risk tiers imply L5 and raise only the
planning and review stages (the implementer keeps its matrix profile)
to `xhigh` / `max`; `--critical` forces the critical tier and `--level` accepts
`L1`-`L5` only. Rules never drive difficulty on their own: the keyword "security"
alone implies no level, and `unknown` is missing information, not confirmed risk.

Inside a session, the route skill runs a code-change route (one with a `pipeline` block)
through `scripts/pipeline.py`: plan, implement, a deterministic test (set
`MODEL_EFFORT_ROUTER_TEST_CMD`), one merged review, and a bounded fix/re-plan loop, each stage
with its own permission mode (plan is read plus the plan file, review is read-only). Only
read-only routes (`pipeline: null`, i.e. `design` / `review`) are delegated with the Agent tool
(`steps[].agent.subagent_type` + `steps[].agent.model`); it cannot set effort, so the subagent
is an `effort-*` agent whose frontmatter pins the matrix effort, and the level instructions
travel at the top of the prompt.

From a terminal, `bin/claude-route -- "<task>"` classifies and then runs the same
`pipeline.py` launcher, so it works without the plugin installed. `--interactive` is limited to
read-only routes and gated `trivial_edit` routes; the latter still runs its deterministic test.
`--print` is accepted and changes nothing.

Route-file replay accepts v2-v7 payloads. Schema v7 records `facts`,
`matched_rules`, `unresolved_facts`, `questions`, `evidence`, `risk_tier`, and `ambiguity` with
`ambiguity_reason`, alongside direct-only
`execution_strategy` and future orchestration `orchestration_eligible` metadata; it
does not enable orchestration on Claude Code. `scripts/astra_adapter.py` is the unchanged
caller-invoked orchestration adapter that revalidates worker inputs and preserves original
verified artifacts; direct v2-v7 route-file replay never invokes it.

## Execution roles and pipeline

Goal: **Opus thinks and verifies, Haiku and Sonnet implement.** Opus designs,
verifies, and reviews; Haiku/Sonnet implement and fix; the launcher runs the tests with no
model; re-promote to Opus when the implementation hits a new design problem.
Classification stays on Haiku.

- Reuse the stored route for follow-up questions in the same task. Re-classify only
  when the task type changes, scope grows a lot, new risk evidence appears, or a
  fact shows the approved design cannot be implemented.
- Test execution (pytest, lint, typecheck, build) runs in the launcher with no model call
  (`MODEL_EFFORT_ROUTER_TEST_CMD` or `--test-cmd`); only a failing log goes to the implementer.
- Do not call Opus after each step. After the implementation and the tests, make one Opus
  verification + code review call for every non-fast code change (High; elevated tier XHigh; critical tier Max),
  sent only the requirement, approved plan, git diff, test results, and key code.
- On review FAIL the reviewer does not fix it: the route's implementer fixes it (every fix
  uses the route's implementer today), then the review runs again; the next failure re-plans
  once. Re-classifying each planned step and each fix to pick Haiku / Sonnet / Opus by
  difficulty is planned, not implemented.
- An implementer that finds something outside the plan stops and returns evidence
  (scope expansion, architecture or public API change, DB migration, security
  boundary change, plan/code mismatch) for an Opus re-plan; "hard" or "unsure" alone
  is not evidence.

See `references/routing-policy.md` for the full rules.


## Validate

```bash
claude plugin validate .
```

## Deterministic CLI fallback

```bash
python3 scripts/router.py --platform claude-code --format command "<task>"
```

For a single-stage route (for example `--task-type implementation --level L1`) this prints a command such as:

```bash
claude -p --model claude-haiku-4-5 --permission-mode acceptEdits -- '<level instructions> <task>'
```

A model with an effort setting adds `--effort <e>` after `--model`. A non-fast code change prints the
plan/implement chain when its planner differs; run it through `scripts/pipeline.py --route-file`
(what `bin/claude-route` does) to get the test gate and review.

`--level` alone is a minimum; `--level` with an explicit `--task-type`
pins both axes and bypasses the preflight.

## Customize

Edit `config/model-map.json` and the agent Markdown files under `agents/` together. Claude Code may clamp an unsupported effort to the highest supported level for the selected model.

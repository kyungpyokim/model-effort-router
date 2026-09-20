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

The router preflights each task with native `claude-sonnet-5` / medium, then uses
`claude-sonnet-5` / medium again once when `needs_context` is true. Claude's JSON-schema output is
read from its `structured_output` result field. Safe mode,
no tools, plan permissions, no session persistence, and a temporary working
directory isolate the classifier. Failure safely selects L3. Each agent pins
`model` and `effort` in frontmatter.

The v5 execution matrix (levels L1-L5, plus a separate risk tier) is:

| task type | L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|
| implementation / local_refactoring | haiku | haiku | sonnet med | sonnet high | opus high -> sonnet high |
| design / review | haiku | opus high | opus high | opus high | opus high |
| architectural_refactoring | haiku | opus high | opus high -> sonnet med | opus xhigh -> sonnet high | opus xhigh -> sonnet high |

`A -> B` is the success-dependent planner-to-implementer chain
(`architectural_refactoring` L3+, and `implementation` / `local_refactoring` at L5).
Read-only design and review use `files_touched: 0`; files only read for context do not
count. The `elevated` and `critical` risk tiers imply L5 and raise only the
planning/judging stage (the planner of a two-stage route, otherwise the single stage)
to `xhigh` / `max`; `--critical` forces the critical tier and `--level` accepts
`L1`-`L5` only. Rules never drive difficulty on their own: the keyword "security"
alone implies no level, and `unknown` is missing information, not confirmed risk.

Inside a session, the route skill delegates each stored step with the Agent tool
(`steps[].agent.subagent_type` + `steps[].agent.model`), so the executor keeps the
session's working directory and edit permissions. The Agent tool cannot set effort, so
the subagent is an `effort-*` agent whose frontmatter pins the matrix effort; the level
instructions travel at the top of the prompt.

From a terminal, `bin/claude-route` starts an interactive session with the selected
model/effort and puts the matching level agent's instructions at the top of the prompt,
so it works without the plugin installed. `--print` forces `claude -p`, which runs with
default permissions and cannot edit files unless your settings allow it.

Route-file replay accepts v2-v5 payloads. Schema v5 records `facts`,
`matched_rules`, `needs_context`, `evidence`, and `risk_tier` alongside direct-only
`execution_strategy` and future orchestration `orchestration_eligible` metadata; it
does not enable orchestration on Claude Code. `scripts/astra_adapter.py` is the unchanged
caller-invoked orchestration adapter that revalidates worker inputs and preserves original
verified artifacts; direct v2-v5 route-file replay never invokes it.

## Execution roles and pipeline

Goal: **Opus thinks and verifies, Haiku and Sonnet implement.** Opus designs,
verifies, and reviews; Haiku/Sonnet implement, fix, and run tests; re-promote to Opus
when the implementation hits a new design problem. Classification stays on Sonnet.

- Reuse the stored route for follow-up questions in the same task. Re-classify only
  when the task type changes, scope grows a lot, new risk evidence appears, or a
  fact shows the approved design cannot be implemented.
- Classify each planned step again (tweak or tests -> Haiku, ordinary logic ->
  Sonnet); test execution (pytest, lint, typecheck, build) belongs to the cheap models.
- Do not call Opus after each step. After steps 1..N and the tests, make one Opus
  verification + code review call (High; elevated tier XHigh; critical tier Max),
  sent only the requirement, approved plan, git diff, test results, and key code.
- On review FAIL the reviewer does not fix it: re-classify the fix (simple -> Haiku, ordinary logic -> Sonnet, design problem -> Opus), then a final Opus review.
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

This prints a command such as:

```bash
claude --model claude-sonnet-5 --effort high -p '<level-4-complex instructions> <task>'
```

`--level` alone is a minimum; `--level` with an explicit `--task-type`
pins both axes and bypasses the preflight.

## Customize

Edit `config/model-map.json` and the agent Markdown files under `agents/` together. Claude Code may clamp an unsupported effort to the highest supported level for the selected model.

# Antigravity Model Effort Router

## Install

From a local directory:

```bash
agy plugin install /absolute/path/to/antigravity-model-effort-router
```

From a Git repository after publishing:

```bash
agy plugin install https://github.com/<owner>/<repo>
```

## Use inside Antigravity

```text
/route <task>
```

This classifies and explains the route, but it does not pretend to replace the model of the already-running session.

The plugin includes L1-L5 level agents under `agents/`. `agy-route` starts a new
session with the account-available model and embeds the matching agent's
instructions in the prompt, so it works without the extension installed.

## Execute with automatic model selection

```bash
./bin/agy-route --interactive -- "<read-only or gated trivial-edit task>"
```

For one-shot mode:

```bash
./bin/agy-route -- "<task>"
```

To execute an already-generated route without classifying or detecting models again:

```bash
./bin/agy-route --route-file /absolute/path/to/route.json
```

Replay preserves `steps[].command`, including the interactive choice saved when
generating JSON with `--interactive`. `--interactive` is single-stage only: the router
refuses it (exit 2) for two-stage routes, which run non-interactively through
`agy-route --route-file` and start the executor only after the planner succeeds. A non-interactive run goes through
`scripts/pipeline.py` (plan -> implement -> launcher-run tests -> merged review).

The router first classifies with native `agy` using fixed
`Gemini 3.8 Flash (Medium)`, print mode, and an isolated sandboxed plan
directory. It disables slash-command expansion and validates native
schema-constrained JSON. The launcher detects available models with `agy models`
before classification and starts the selected profile. Classifier failures
safely select L3.
In Antigravity, effort is represented in names such as `Gemini ... Flash (Low)` or `Claude ... (Thinking)` rather than a separate `--effort` flag.

Levels are L1-L5. A separate risk tier (`elevated` for security/payment logic changes
and similar, `critical` for irreversible/ledger/crypto work or `--critical`) implies L5
and, because Antigravity has no effort setting, swaps the planning and review stages to
`Claude Opus Thinking`; the implementer stage keeps its matrix model. `--level` accepts
`L1`-`L5` only.

Route-file replay accepts v2-v7 payloads. Schema v7 records `facts`,
`matched_rules`, `unresolved_facts`, `questions`, `evidence`, `risk_tier`, direct-only `execution_strategy`,
and future orchestration `orchestration_eligible` metadata; it
does not enable orchestration on Antigravity. `scripts/astra_adapter.py` is the unchanged
caller-invoked orchestration adapter that revalidates worker inputs and preserves original
verified artifacts; direct v2-v7 route-file replay never invokes it.

## Execution roles and pipeline

Spend top-model tokens on important judgement and run already-decided work on the
cheapest sufficient model: the strongest available model (Pro High / Opus Thinking)
plans, designs, verifies, and reviews; Flash and Sonnet Thinking implement and fix; the
launcher runs the tests with no model. Reuse the stored route for same-task follow-ups (re-classify only on a
task-type change, large scope growth, new risk evidence, or a fact that shows the
approved design cannot be implemented). Do not call the strong model after each step:
after the implementation and the tests, make one merged verification + review call for every non-fast code change
sent only the requirement, approved plan, git diff, test results, and key code. On review
FAIL the route's implementer fixes it (the reviewer does not); the next failure re-plans once.
Non-fast code changes get a planner from the `design` row at `max(level, L2)`, except that Antigravity L2 code
changes stay single-stage (Flash High plans and implements alike, so the review is a self-review by the same Flash model until reviewer separation lands in Phase 3); only a gated `trivial_edit` skips plan and review. The router does not enforce per-stage permissions on Antigravity (planned). An implementer that finds
something outside the plan (scope expansion, architecture or public API change, DB
migration, security boundary change, plan/code mismatch) stops and returns evidence;
"hard" or "unsure" alone is not evidence. See `references/routing-policy.md`.

## Customize

Edit the ordered regular expressions and fallbacks under `platforms.antigravity` in `config/model-map.json`.

## Validate

```bash
agy plugin validate .
```

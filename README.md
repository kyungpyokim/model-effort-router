# Model Effort Router (v3.0.0)

English | [한국어](README.ko.md)

A cross-platform bundle that routes a coding task to one model-and-effort
profile for Codex, Claude Code, or Antigravity.

All three platforms share the same two-dimensional routing: a `task_type` axis
(implementation, design, review, local_refactoring, architectural_refactoring)
and the difficulty level (L1–L5), plus a separate risk tier (`standard`,
`elevated`, `critical`) that raises the planning/judging effort for high-risk work.
Both are mapped onto each platform's own models (Codex: luna/terra/sol —
Claude Code: haiku/sonnet/opus — Antigravity: Flash/Pro/Sonnet Thinking/Opus Thinking).

Overall principle: spend top-model tokens on important judgement, and run
already-decided work on the cheapest sufficient model. Codex: **Sol thinks and
verifies, Luna and Terra implement.** Claude Code: **Opus thinks and verifies,
Haiku and Sonnet implement.** See [Execution roles and pipeline](#execution-roles-and-pipeline).

## Cascading preflight classifier

The classifier never scores difficulty. It answers seventeen bounded facts about
the work (files touched, module or service boundaries, whether the result is known,
new structure, security/payment logic changed or reviewed, the security domain,
public API, persisted data, irreversible changes, trust-boundary changes, blast
radius, silent material harm), and `DIFFICULTY_RULES` in
`scripts/router.py` turn those facts into the level. The highest matching rule wins; `matched_rules` in the route JSON names it.
When a fact that decides L4 or above is `unknown`, the router escalates once to a
repository-aware classifier. Some unknowns only ask for that escalation without raising
the level: `crosses_module_boundary`, `intermittent_or_concurrency`,
`changes_trust_boundary`, `blast_radius`, and `silent_failure_material_harm`. A
`crosses_service_boundary` still unknown after escalation keeps the L4 floor, and an
unknown `irreversible_or_ledger_or_crypto` floors at L5 but never triggers the critical
tier. The escalated classifier read the repository, but only some safety facts may
be lowered by it. A sticky safety fact the first reply affirmed (security/payment
change, persisted data, public API, irreversible, trust boundary, silent harm) is
OR-aggregated and can never be lowered by the escalated reply. A correctable safety
fact (critical security domain, security review, broad blast radius) — where a
keyword-driven primary produces most of its false positives — may be corrected once
the escalated reply gives an explicit, non-`unknown` answer: an explicit no/narrow
wins, `none` wins, and a differing named domain keeps whichever of the two is more
critical by priority (payment > crypto > auth > permissions > pii > secrets).

Escalation models by platform:

- **Codex**: `gpt-5.6-luna` (medium) → `gpt-5.6-terra` (medium)
- **Claude Code**: `claude-sonnet-5` (medium) → `claude-sonnet-5` (medium)
- **Antigravity**: `Gemini 3.8 Flash (Medium)` → `Gemini 3.1 Pro (High)`

Each preflight runs in an isolated temporary directory and validates structured JSON
(task_type, facts, delegability, evidence, reason) before selecting a profile. `files_touched`
accepts `0` for read-only design and review work. In a Claude Code
or Codex session the route skill runs the same prompt through an in-session
`difficulty-assessor` agent instead and passes its JSON with `--classification-file`. When
repository context is needed, it passes a `primary`/`escalated` JSON envelope so the router
combines both replies before selecting the route.

A non-zero preflight exit is retried once; a timeout is not. If it
still fails, cannot start, or returns invalid JSON:

- On a terminal, the router asks for `task_type` and `level` (or `critical`) on
  stderr and routes that answer through the deterministic matrix, so you get a
  real route instead of a guess. `--no-prompt` skips this.
- Otherwise it prints the safe fallback route (implementation / L3 / safe
  baseline) on stdout, reports the failure on stderr, and exits non-zero — so a
  `set -e` launcher stops before running the guessed route.

```bash
python3 scripts/router.py --platform codex --format json "여러 서비스의 OAuth 인증 장애를 분석하고 수정"
```

Pin the task type when you already know it; level and risk flags are still
classified:

```bash
python3 scripts/router.py --platform codex --task-type design "결제 데이터 마이그레이션 설계"
```

To classify once and execute exactly that route, save the JSON and replay it:

```bash
python3 scripts/router.py --platform codex --format json "작업" > /tmp/model-effort-route.json
plugins/codex-model-effort-router/bin/codex-route --route-file /tmp/model-effort-route.json
```

The JSON also includes `verification.recommended` and `verification.skipped`.
They identify repository-agnostic checks with reasons; they are not shell
commands or execution results. The selected executor receives recommended
checks, selects applicable existing repository checks, and reports each result
or why it was not run. Route-file replay ignores this JSON guidance and
reuses only the stored execution steps.

### Chained pipeline

Non-interactive launcher runs (`codex-route`, `claude-route`, `agy-route`) execute
`scripts/pipeline.py`: plan -> implement -> deterministic test -> one merged Sol/Opus review.
Tests run in the launcher without a model call: set `MODEL_EFFORT_ROUTER_TEST_CMD` (or pass
`--test-cmd` to `pipeline.py`). Only a failure sends a truncated log to the implementer.
L4+ code changes get the review at the risk tier's effort; a review FAIL is fixed once, the next
failure re-plans once, and then the run stops. Claude implement/fix stages run with `acceptEdits`; plan and review stages cannot edit code. Route files may only carry router-generated argv shapes. The launcher logs one `phase=...` line per stage (`MODEL_EFFORT_ROUTER_VERBOSE=1` adds the commands). Route (who) and execution state (where the run
is, `state.json`) stay separate. Details: `references/routing-policy.md`.

### Live classifier benchmark

`scripts/eval_router_performance.py --live-classifier --platform codex|claude-code|antigravity [--case NAME ...] [--limit N]` sends the labelled corpus to the real classifier and reports routing accuracy (task type, level, tier, `needs_context`), model+effort profile agreement (so a Luna medium vs Luna high or Haiku vs Sonnet low miss is visible), labelled-fact accuracy per fact, the `requires_code_understanding` confusion counts, unknown transitions, classifier fallbacks, calls and seconds. It spends real model usage, so it is opt-in. A case that does not label `requires_code_understanding` is graded on the classifier's own answer for that fact when comparing profiles.

### Route reuse

Set `MODEL_EFFORT_ROUTER_SESSION=<key>` (or `router.py --session <key>`) for a task thread. The first
task is classified and stored; follow-ups in the same workspace reuse that route without calling the
classifier, until the workspace changes, 4 hours pass, a run re-plans or fails, or the new task shows a
different operation, wider scope, or new risk evidence. `--no-reuse` forces a fresh classification.

Route JSON emits schema v6: `facts`, `matched_rules`, `needs_context`, and
`evidence` replace the old score fields, and `risk_tier` (`standard`, `elevated`,
`critical`) is recorded next to the level. It records `execution_strategy: "direct"` and
`orchestration_eligible` separately: eligibility is only a Codex orchestration handoff
candidate, never an execution request. `scripts/astra_adapter.py` is the unchanged
local, caller-invoked orchestration adapter (an isolated-worker boundary that requires
supplied route and manifest digests, revalidates worker input copies, and preserves the
original verified artifacts after each attempt). Direct v2-v6 route-file replay never
invokes it.

`delegability` is independent of the difficulty rules: `0` is shared
state, sequence-dependent, risky, or tightly coupled work; `1` remains coupled;
`2` requires independent subtasks with explicit ownership and verification. Only
safe Codex single routes at L5 with `delegability: 2` (never the critical tier) can be eligible.

Risk policy lives in code, not in prompts. The LLM classifies facts; rules only
guarantee a minimum for confirmed high-risk work. The keyword "security" alone never
implies a level, and `unknown` is missing information, not confirmed risk.

- **Levels** are `L1`–`L5` only. Security, authentication, authorization, or payment
  flags force the **elevated** risk tier (which implies L5) with Autobahn scope
  guards; data migration and public API changes force an L4 floor. Review-only
  security work is floored by facts rather than flags: `reviews_security_sensitive_code`
  gives at least L4 and a critical `security_domain` (payment, crypto, auth,
  permissions, pii) at least L5, whatever the task type.
- **`elevated` tier** (L5): a security/payment logic change, a critical domain whose
  trust boundary changes, an intermittent failure across services, or new structure
  across services with an open result. It raises the planning/judging stage effort to
  `xhigh` on Codex (Sol) and Claude Code (Opus); Antigravity, which has no effort
  setting, swaps that stage to Claude Opus Thinking.
- **`critical` tier** (L5): `irreversible_or_ledger_or_crypto` = yes (irreversible
  production data, ledger correctness, new cryptography), or the `--critical` flag.
  Same stage raised to `max` (Antigravity: Claude Opus Thinking). Only an explicit yes
  fires it; an unknown never does.
- The implementer stage of a two-stage route keeps its matrix profile; only the
  planning/judging stage is raised. Tier profiles live under `tiers` in
  `config/model-map.json`.

Payment means monetary consequence: moving money, deciding the amount charged
(price, discount, tax), authorizing, capturing, cancelling, or refunding, ledger or
settlement correctness, or a monetary obligation. Code that only lives in a billing or
order module, or that caches or reads billing data, is not payment. Permissions covers
access boundaries, including tenant and customer data isolation and the cache keys or
namespaces that hold per-customer data.

For Antigravity, detect account-local models before printing its command:

```bash
python3 scripts/router.py --platform antigravity --detect-antigravity-models --format command "간헐적인 멀티서비스 장애의 근본 원인 분석"
```

`--level` (`L1`–`L5`) alone is a minimum over the classified level. `--level` or
`--critical` together with an explicit `--task-type` skips the preflight because both
axes are pinned; the pinned level is used as is, and `--critical` pins L5 with the
critical tier. `--level critical`, `L6`, and `L7` are no longer valid. Fallbacks are
always reported on stderr.

## Two-stage routes

On every platform, `architectural_refactoring` at L3+ and
`implementation` / `local_refactoring` at L5 run as a success-dependent shell
chain: the planner (Codex `sol`, Claude Code `opus`, Antigravity Pro) writes a structured plan JSON
into a temporary run directory, then the implementer (`luna`/`terra`, or
`sonnet`) reads the plan plus the repository and implements it with the plan's
validation commands. The implementer does not make new design decisions: it stops
and returns escalation evidence for the planner instead. The run directory is
removed on success and preserved on any failure (`--keep-plan` forces
preservation).

```bash
python3 scripts/router.py --platform codex --task-type architectural_refactoring --level L5 "모듈 경계 재분리" --format command
```

## Execution roles and pipeline

Use strong models for plan, design, verify, and review; cheap models for implement,
fix, and test. Role + difficulty + risk decide the model and effort: the same L4
maps to Sol/Opus for design, review, or verification and to Terra high / Sonnet
high for implementation. Roles map onto the existing task types: design =
`design`, review = `review`, implementation = `implementation`, `local_refactoring`,
and `architectural_refactoring` (which already plans with Sol/Opus and implements with
Terra/Sonnet). Classification stays cheap.

```text
request -> classify (cheap) -> plan/design (Sol / Opus)
        -> per planned step: re-classify the step -> implement + run tests
             (Luna med / Haiku for tweaks and tests, Terra / Sonnet for logic)
             new design problem? stop -> evidence -> Sol / Opus re-plan
        -> after steps 1..N: ONE Sol / Opus verification + review
             (High; elevated tier XHigh; critical tier Max)
        -> FAIL: re-classify the fix (simple -> Luna med / Haiku, ordinary logic ->
             Terra / Sonnet, design problem -> Sol / Opus) -> final Sol / Opus review
```

- **Planning and implementation difficulty are separate.** A hard task (for example
  redesigning the router's security hard floor) is designed by Sol/Opus; each resulting
  step is classified again. The planner does not have to implement.
- **Test execution** (pytest, lint, formatter, typecheck, build) runs on the cheap
  implementation models; the final "does this satisfy the requirement?" verification is
  Sol/Opus.
- **One merged review.** Do not call Sol/Opus after every step. Batch steps 1..N, run
  tests, then make one call that merges verification and code review, sent only the
  original requirement, approved plan, git diff, test results, and key code (never
  the whole session).
- **Review FAIL:** the reviewer does not fix it; the fix is re-classified as above.
- **Escalation is evidence-only.** An implementer that finds something outside the plan
  stops and returns evidence: scope expansion, architecture change, public API change,
  DB migration, security boundary change, or a plan that no longer matches the code.
  "It's hard" or "I'm unsure" alone is not a valid reason.
- **Follow-ups reuse the stored route.** Re-classify only when the task type changes
  (for example INSPECT to MODIFY), the scope grows a lot, new risk evidence appears, or
  a fact shows the approved design cannot be implemented.
- **Effort ceilings.** Luna low/medium/high (beyond Luna high, move to Terra rather than
  Luna xhigh); Terra medium/high; Sol high/xhigh/max (Sol and Opus never run design, review, or planning below high). Claude Code: Haiku for simple work,
  Sonnet for general-to-complex implementation, Opus for plan/design/verify/review. The
  current matrix reaches Luna high and Sonnet low only through the L2 refinement: a simple
  implementation that needs existing-code understanding (`requires_code_understanding`) gets Luna
  high / Sonnet low, otherwise L2 stays Luna medium / Haiku.

The full rule set and matrices are in [references/routing-policy.md](references/routing-policy.md).

## Bundle layout

```text
plugins/
  codex-model-effort-router/
  claude-model-effort-router/
  antigravity-model-effort-router/
config/model-map.json
scripts/router.py
scripts/sync_bundle.py
```

## Install

Install all three for the current user:

```bash
python3 scripts/install_plugins.py all --scope user
```

Use `--scope project` for a project-local Claude Code installation and
`--dry-run` to preview installation commands.

### Codex route-first hook

The Codex plugin includes a small SessionStart policy hook. It reminds Codex to
route a new substantive coding task before repository work, but does not run a
classifier or worker and does not reject a prompt. Codex requires a separate trust
approval for the installed hook definition. For a guaranteed routed new process,
use `plugins/codex-model-effort-router/bin/codex-route -- "<task>"`.

## Customize model names

Edit `config/model-map.json`, then run `python3 scripts/sync_bundle.py` to
propagate the shared files into every plugin copy. The Codex section is a
`task_type × level` matrix; single-stage rows define `model` + `effort`, and
two-stage rows define a `stages` list. The Antigravity map uses ordered regular
expressions because `agy models` output varies by account and release channel.
Agent TOML files carry no model pins: normal route execution always decides
model and effort at runtime from this map.

The optional `orchestration.codex` policy is fail-closed. `enabled: false` is
the shipped default and does not change `execution_strategy`; it only preserves
candidate metadata for a later adapter release.

## Validate

```bash
python3 scripts/validate_bundle.py
python3 -m unittest discover -s tests -v
```

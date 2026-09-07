# Model Effort Router (v2.0)

A cross-platform bundle that routes a coding task to one model-and-effort
profile for Codex, Claude Code, or Antigravity.

All three platforms share the same two-dimensional routing: a `task_type` axis
(implementation, design, review, local_refactoring, architectural_refactoring)
and the difficulty level (L1–L7 plus Critical Override), mapped onto each platform's
own models (Codex: luna/terra/sol/astra — Claude Code: haiku/sonnet/fable/opus —
Antigravity: Flash/Pro/Sonnet Thinking/Opus Thinking).

## Cascading preflight classifier

The CLI router evaluates tasks with a lightweight primary classifier and escalates to
a mid-tier fallback model when confidence is low (< 0.80):

- **Codex**: `gpt-5.6-luna` (medium) → `gpt-5.6-terra` (medium)
- **Claude Code**: `claude-haiku-4-5` (N/A) → `claude-sonnet-5` (medium)
- **Antigravity**: `Gemini 3.8 Flash (Medium)` → `Gemini 3.1 Pro (High)`

Each preflight runs in an isolated temporary directory and validates structured JSON
(task_type, six factor scores, six risk flags, confidence, context_required, delegability, reason) before selecting
a profile.

If the selected classifier times out, cannot start, fails, or returns invalid
JSON, routing uses the safe fallback: implementation / L3 / safe baseline.

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

Route JSON now emits schema v3. It records `execution_strategy: "direct"` and
`orchestration_eligible` separately: eligibility is only a Codex Astra handoff
candidate, never an execution request. `scripts/astra_adapter.py` is a local,
caller-invoked isolated-worker boundary that requires supplied route and manifest
digests. Direct v2 and v3 route-file replay never invokes it.

`delegability` is independent of the six-factor difficulty score: `0` is shared
state, sequence-dependent, risky, or tightly coupled work; `1` remains coupled;
`2` requires independent subtasks with explicit ownership and verification. Only
safe Codex single routes at L5–L7 with `delegability: 2` can be eligible.

Risk policy lives in code, not in prompts: security, authentication,
authorization, or payment flags force an L6 floor with Autobahn scope guards;
data migration and public API changes escalate one level each.

For Antigravity, detect account-local models before printing its command:

```bash
python3 scripts/router.py --platform antigravity --detect-antigravity-models --format command "간헐적인 멀티서비스 장애의 근본 원인 분석"
```

`--level` is a minimum. An explicit `--level L7` or `--critical` together with an
explicit `--task-type` skips the preflight because both axes are pinned; explicit
factors override only those classifier scores. Fallbacks are always reported on stderr.

## Two-stage architectural refactoring

On Codex, `architectural_refactoring` at L3+ runs as a success-dependent shell
chain: `sol` writes a structured plan JSON into a temporary run directory,
then the executor (`luna`/`terra`) reads the plan plus the repository and
implements it with the plan's validation commands. The run directory is
removed on success and preserved on any failure (`--keep-plan` forces
preservation).

```bash
python3 scripts/router.py --platform codex --task-type architectural_refactoring --level L5 "모듈 경계 재분리" --format command
```

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

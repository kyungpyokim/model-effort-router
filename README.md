# Model Effort Router

A cross-platform bundle that routes a coding task to one model-and-effort
profile for Codex, Claude Code, or Antigravity.

All three platforms share the same two-dimensional routing: a `task_type` axis
(implementation, design, review, local_refactoring, architectural_refactoring)
and the difficulty level (L1-L5), mapped onto each platform's own models
(Codex: luna/sol/terra — Claude Code: haiku/sonnet/opus — Antigravity:
Flash/Pro/Sonnet·Opus Thinking).

## Preflight classifier

The CLI router uses the native CLI for the selected platform: Codex uses
`gpt-5.6-terra` / low, Claude Code uses `claude-sonnet-5` / low, and
Antigravity uses `gemini-3.6-flash-low`. Each preflight runs in an isolated
temporary directory and validates structured JSON (task_type, factor scores,
risk flags, confidence) before selecting a profile. This requires the selected
platform's installed, authenticated CLI.

If the selected classifier times out, cannot start, fails, or returns invalid
JSON, routing uses the safe fallback: implementation / L3 / luna xhigh. No
keyword, Korean-particle, or homonym matching is used.

```bash
python3 scripts/router.py --platform codex --format json "여러 서비스의 OAuth 인증 장애를 분석하고 수정"
```

Pin the task type when you already know it; level and risk flags are still
classified:

```bash
python3 scripts/router.py --platform codex --task-type design "결제 데이터 마이그레이션 설계"
```

Risk policy lives in code, not in prompts: security, authentication,
authorization, or payment flags force an L4 floor; data migration and public
API changes escalate one level each.

For Antigravity, detect account-local models before printing its command:

```bash
python3 scripts/router.py --platform antigravity --detect-antigravity-models --format command "간헐적인 멀티서비스 장애의 근본 원인 분석"
```

`--level` is a minimum. An explicit `--level L5` together with an explicit
`--task-type` skips the preflight because both axes are pinned; `--level L5`
alone still classifies to pick the right matrix row. Explicit factors override
only those classifier scores. Fallbacks are always reported on stderr.

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

## Validate

```bash
python3 scripts/validate_bundle.py
python3 -m unittest discover -s tests -v
```

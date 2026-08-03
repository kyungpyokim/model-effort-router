# Model Effort Router

A cross-platform bundle that routes a coding task to one model-and-effort
profile for Codex, Claude Code, or Antigravity.

## Preflight classifier

The CLI router asks the installed Codex CLI to classify the task with fixed
`gpt-5.6-terra` / low effort. The response is constrained by a JSON schema and
validated before it selects a profile. The preflight runs ephemerally in a
temporary read-only directory without project or user rules.
This requires an installed, authenticated Codex CLI.

If Codex times out, cannot start, fails, or returns invalid JSON, routing uses
the safe L3 profile. No keyword, Korean-particle, or homonym matching is used.

```bash
python3 scripts/router.py --platform codex --format json "여러 서비스의 OAuth 인증 장애를 분석하고 수정"
```

Print a launch command:

```bash
python3 scripts/router.py --platform claude-code --format command "결제 데이터 마이그레이션 설계와 회귀 테스트"
```

For Antigravity, detect account-local models before printing its command:

```bash
python3 scripts/router.py --platform antigravity --detect-antigravity-models --format command "간헐적인 멀티서비스 장애의 근본 원인 분석"
```

`--level` is a minimum. L1-L4 still run preflight so a semantic L4/L5 floor
cannot be lowered; `--level L5` bypasses it because L5 is already maximal.
Explicit factors override only those Terra scores, then preserve any higher
semantic level returned by the preflight. A fallback is reported on stderr,
including with `--format command`, so launchers never hide an L3 fallback.

## Bundle layout

```text
plugins/
  codex-model-effort-router/
  claude-model-effort-router/
  antigravity-model-effort-router/
config/model-map.json
scripts/router.py
```

For Antigravity, use `--detect-antigravity-models` to select an account-local
model after the Terra classification.

## Install

Install all three for the current user:

```bash
python3 scripts/install_plugins.py all --scope user
```

Use `--scope project` for a project-local Claude Code installation and
`--dry-run` to preview installation commands.

## Customize model names

Edit `config/model-map.json`, then mirror that map in the platform agents. The
Antigravity map uses ordered regular expressions because `agy models` output
varies by account and release channel.

## Validate

```bash
python3 scripts/validate_bundle.py
python3 -m unittest discover -s tests -v
```

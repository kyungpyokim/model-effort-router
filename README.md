# Model Effort Router

A cross-platform plugin bundle that scores a coding task by difficulty and selects a model-and-effort profile for:

- OpenAI Codex
- Claude Code
- Google Antigravity CLI / IDE

## Difficulty levels

| Level | Meaning | Typical work |
|---|---|---|
| L1 | Simple | Rename, copy change, local lookup, one-file mechanical edit |
| L2 | Standard | Clear feature, focused bug fix, unit tests |
| L3 | Complex | Multi-file implementation, non-trivial debugging, broad refactor |
| L4 | Advanced | Architecture, cross-service changes, security-sensitive work, production migrations |
| L5 | Critical | Irreversible data changes, cryptography, compliance, financial correctness, high-blast-radius incidents |

The score uses six 0-2 factors: scope, ambiguity, diagnosis, design, risk, and verification. See `references/routing-policy.md`.

## Bundle layout

```text
plugins/
  codex-model-effort-router/
  claude-model-effort-router/
  antigravity-model-effort-router/
config/model-map.json
scripts/router.py
scripts/install_plugins.py
```

## Test the router

```bash
python3 scripts/router.py \
  --platform codex \
  --format json \
  "여러 서비스의 OAuth 인증 장애를 분석하고 수정"
```

Print a launch command:

```bash
python3 scripts/router.py \
  --platform claude-code \
  --format command \
  "결제 데이터 마이그레이션 설계와 회귀 테스트"
```

For Antigravity, detect the models available to the current account:

```bash
python3 scripts/router.py \
  --platform antigravity \
  --detect-antigravity-models \
  --format command \
  "간헐적인 멀티서비스 장애의 근본 원인 분석"
```

## Install

Install all three for the current user:

```bash
python3 scripts/install_plugins.py all --scope user
```

Project-local installation:

```bash
python3 scripts/install_plugins.py all --scope project
```

Preview installation commands first with `--dry-run`. Each plugin directory also contains platform-specific installation and verification instructions.

## Customize model names

Edit `config/model-map.json`, then mirror the new mapping in the platform agents. The Antigravity map uses ordered regular expressions because `agy models` output varies by account and release channel.

## Validate

```bash
python3 scripts/validate_bundle.py
python3 -m unittest discover -s tests -v
```

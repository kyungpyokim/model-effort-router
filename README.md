# model-effort-router

개발 요청의 난이도(L1~L5)와 위험 신호를 판정하고, 그에 맞는 모델과 reasoning effort로 작업을 실행하는 도구입니다. Codex와 Claude Code에서 동작합니다.

- **`mer` CLI (주 경로)**: 요청을 분류합니다. 고른 모델·effort로 세션 하나를 실행하고 Test Gate를 돌립니다. 실패하면 같은 세션을 다음 프로필로 이어서 승격하고, 위험한 작업에는 독립 읽기 전용 Review를 붙입니다.
- **UserPromptSubmit hook (보조)**: 일반 세션에서 난이도, 위험 플래그, 추천 모델·effort, 계획 먼저·리뷰 권고를 짧게 덧붙입니다. 권고만 하고 아무것도 막거나 강제하지 않습니다.

Python 3 표준 라이브러리만 씁니다(외부 의존성 없음). 런타임 코드는
`model_effort_router/`에 한 번 설치하고, 세 플러그인은 그 런타임을 import합니다.

## 난이도와 세션 프로필

| Level | 의미 | 시작 프로필 | 승격 1 | 승격 2 | 독립 Review |
|---|---|---|---|---|---|
| L1 | 기계적 변경 | economy / medium | economy / high | balanced / high | 없음 |
| L2 | 국소 변경 | economy / medium | balanced / high | frontier / high | 없음 |
| L3 | 여러 파일, 설계 판단 | balanced / high | frontier / high | frontier / xhigh | 없음 |
| L4 | 구조 변경 | frontier / high | frontier / xhigh | 중단 후 보고 | frontier / high |
| L5 | 고난도·고위험 | frontier / xhigh | 중단 후 보고 | — | frontier / xhigh |

- 승격 조건은 Test Gate `failed`뿐입니다. Review가 `changes_requested`를 내면 승격하지 않고, 같은 세션에서 한 턴 동안 지적을 반영한 뒤 Gate만 다시 돕니다.
- `auth`·`security` 신호가 있으면 L1~L3에도 독립 Review가 붙습니다. 위험 신호가 있으면 계획 먼저 쓰기도 붙습니다.
- 추상 프로필은 호스트 adapter가 실제 모델로 바꿉니다.

| tier | Codex | Claude Code |
|---|---|---|
| economy, balanced | gpt-6-luna | claude-sonnet-5-5 |
| frontier | gpt-6.1-sol | claude-opus-5-5 |

Claude Code에서는 `xhigh`가 `high`로 매핑됩니다. 파일럿에서 Opus xhigh가 비용만 크게 늘렸기 때문입니다.

## 설치

플러그인에는 `mer` CLI, host별 manifest, skill, hook만 들어 있습니다. 공통
런타임은 플러그인 설치와 별도로 한 번 설치해야 합니다. 먼저 저장소를 clone한
뒤 같은 checkout에서 설치하세요.

```bash
git clone https://github.com/kyungpyokim/model-effort-router-next.git
cd model-effort-router-next
python3 scripts/install_core.py
python3 scripts/install_core.py --check
```

기본 설치 위치는 `${XDG_DATA_HOME:-~/.local/share}/model-effort-router/runtime`입니다.
`MER_CORE_PATH`를 절대 경로로 지정하면 개발 checkout을 런타임으로 사용할 수 있습니다.

```bash
claude plugin marketplace add kyungpyokim/model-effort-router-next
claude plugin install model-effort-router@model-effort-router
```

```bash
codex plugin marketplace add kyungpyokim/model-effort-router-next
codex plugin add model-effort-router@model-effort-router
```

설치하거나 업데이트한 뒤 호스트를 재시작하고 `/hooks`에서 hook을 신뢰해야 합니다. 신뢰하기 전까지 hook은 아무 출력도 내지 않습니다. 업데이트 방법과 세부 동작은 [Claude Code 플러그인 README](plugins/claude-model-effort-router/README.md)와 [Codex 플러그인 README](plugins/codex-model-effort-router/README.md)에 있습니다.

## 사용

```bash
python3 <plugin>/bin/mer run --dry-run --level L3 'add pagination to the orders API'
```

```bash
python3 <plugin>/bin/mer run 'add pagination to the orders API'
```

```bash
python3 <plugin>/bin/mer chat 'add pagination to the orders API'
```

- `run`: 분류 → 세션 실행 → Test Gate → 승격 → Review까지 한 번에 진행합니다. 종료 코드 0은 Gate가 실패하지 않았고, 필요한 Review가 승인되었거나 지적이 반영되었다는 뜻입니다. 깨끗한 작업 트리에서 실행하세요(Review는 HEAD 기준 diff를 봅니다).
- `chat`: 분류만 하고, 고른 모델·effort로 대화형 세션을 엽니다.
- `--dry-run`: 결정, 사다리, 첫 명령만 출력하고 세션을 시작하지 않습니다. 모델을 호출하는 분류기도 부르지 않으며, `--level`로 레벨을 정하거나 `--classify`로 분류 호출 1회를 허용합니다.
- 요청 첫 줄 override: `/router off`, `/router session=frontier:high`. override로도 위험 신호의 Review 하한은 없앨 수 없습니다.
- 안전 우회 플래그(`--dangerously-*`, bypassPermissions)는 어디서도 쓰지 않습니다. Review 세션은 Read/Grep/Glob만 씁니다.

## 설정

설정 파일은 두 곳에 둘 수 있고, repo 설정이 user 설정보다 우선합니다.

- repo: `.model-effort-router.json`
- user: `${XDG_CONFIG_HOME:-~/.config}/model-effort-router/config.json`

```json
{
  "router": {"mode": "auto"},
  "difficulty": {"backend": "jev", "fallback": "nimble", "timeout_s": 10},
  "gate": {"checks": {"test": "python3 -m unittest"}},
  "session": {"subagent_policy": "level", "claude_context": "lean"}
}
```

난이도 Backend는 넷 중에서 고릅니다.

| Backend | 위치 | 비용 | corpus-v1 exact / under / critical miss |
|---|---|---|---|
| `subscription` (기본) | 호스트 구독 모델 1회 호출 | 구독 사용량 | — |
| `jev` | TypeSafe API (`TYPESAFE_API_KEY` 필요, 요청 텍스트 전송) | 호출당 과금 | 82% / 5 / 0 |
| `nimble` | 로컬 Ollama (`ollama pull nimble`, loopback 주소만 허용) | 무료 | 78% / 21 / 1 |
| `nimble_jev` | Nimble 먼저, 불확실·범위 한정·위험 신호일 때만 Jev (`ollama pull nimble`과 `TYPESAFE_API_KEY` 둘 다 필요; Ollama가 꺼져 있거나 nimble을 받지 않았으면 모든 프롬프트가 TypeSafe로 간다; 선택된 경우(그 300건에서 약 71%)만 텍스트가 TypeSafe로 전송) | Jev 호출 수만큼 | corpus-v3의 새 케이스 300건(레벨 있는 270건, 합성 AI 라벨) 260/270 exact, critical miss 1/127 (Jev 단독 같은 270건에서 263/270; 비용·지연 우위는 미입증) |

권장 조합은 Jev를 기본으로 두고 Nimble을 fallback으로 쓰는 것입니다.

- **Test Gate 명령**: 설정에 없으면 AGENTS.md·CLAUDE.md, CI 파일, `package.json`·`pyproject.toml`·`Makefile` 순서로 찾습니다. 찾지 못한 검사는 통과가 아니라 `not_run`으로 보고합니다.
- **로그**: `${XDG_STATE_HOME:-~/.local/state}/model-effort-router/`에 남습니다. 프롬프트 원문은 남기지 않고 해시와 길이만 기록합니다.

## 측정 결과 (요약)

Claude Code 파일럿 13건(c3, 2026-10-04)의 결과입니다.

- 13건 모두 정상 종료했고, 저장된 diff를 다시 적용하면 전부 테스트를 통과했습니다.
- 비용은 $3.28입니다.
  - Sonnet 고정 기준선 $3.13보다 5% 많습니다.
  - Opus 고정 기준선 $5.72보다 43% 적습니다.
- Review가 없는 9건만 보면 Sonnet 기준선보다 28% 적습니다.

수치와 방법은 [기획서](docs/plans/model-effort-router-pluggable-difficulty-plan.md)의 §22와 Phase 5·6에 있습니다.

## 저장소 구조

```
model_effort_router/   공유 Router Core: difficulty backend, policy, host adapter/exec, gate, CLI
  entrypoints.py      플러그인 공통 진입점과 RUNTIME_API 호환성 검사
plugins/               Codex·Claude Code·Antigravity 플러그인 (bin/mer, skills, 지원 호스트의 hooks)
evaluation/            코퍼스, backend 비교, 비용 기준선, 파일럿 (플러그인에 미포함)
docs/                  기획서, 평가 사용법, 호스트 spike 기록
scripts/install_core.py 공유 core 설치 및 `--check`
tests/                 unittest
```

## 개발

```bash
python3 -m unittest discover -s tests
```

```bash
python3 scripts/install_core.py --check
```

- `model_effort_router/`를 고친 뒤에는 `python3 scripts/install_core.py`로 공유 런타임을 갱신하고 `--check`로 확인합니다.
- 플러그인의 `bin/`·hook은 설치된 공유 런타임의 `entrypoints.py`를 import합니다. CLI와 gate는 런타임 누락·손상·API 불일치를 stderr에 안내하고 종료 코드 2를 반환하며, hook은 조용히 종료 코드 0을 반환합니다.
- `RUNTIME_API`가 바뀌는 호환성 변경은 플러그인과 런타임을 함께 업데이트해야 합니다. 플러그인 업데이트만으로는 공유 런타임이 갱신되지 않습니다.
- 플러그인을 바꿀 때마다 `plugin.json`의 `version`을 올리세요. 같은 버전이면 업데이트가 건너뜁니다.
- 평가 도구 중 모델을 호출하는 경로는 `--live`를 붙여야만 실행됩니다. 사용법은 [docs/evaluation/README.md](docs/evaluation/README.md)에 있습니다.

## 알려진 한계

- hook은 fail-open입니다. 오류, 타임아웃, 미신뢰 상태에서는 권고가 나오지 않습니다.
- 다음 항목은 아직 live로 확인하지 못했습니다.
  - Claude Code 승격 경로(파일럿에서 승격이 일어난 적이 없음)
  - L5 subagent 토큰이 usage에 집계되는지
- 보정값(Jev 0.6/0.8, Nimble 0.2)은 corpus-v1에서 정했으므로 과적합 위험이 있습니다. 사람 라벨과 별도 코퍼스로 다시 확인해야 합니다.

# Model Effort Router

영문판: [README.md](README.md)

MER(Model Effort Router)는 개발 요청을 **역할 + 노력 수준**으로 분류하고, 해당 조합에 맞는 호스트 모델을 추천합니다. MER의 범위는 모델·effort 선정이며 작업 실행, 리뷰, 수정은 호스트가 처리합니다. 추천은 현재 턴의 설정을 자동 변경하지 않습니다.

## 설치

호스트 플러그인에는 공유 runtime이 포함되어 있지 않습니다. 먼저 저장소를 복제하고 runtime을 설치합니다.

```sh
git clone https://github.com/kyungpyokim/model-effort-router.git
cd model-effort-router
python3 scripts/install_core.py
python3 scripts/install_core.py --check
```

그다음 저장소 루트에서 사용할 호스트 플러그인을 설치합니다.

**Codex CLI** — 이 저장소의 Codex marketplace를 등록하고 플러그인을 설치합니다.

```sh
codex plugin marketplace add https://github.com/kyungpyokim/model-effort-router --sparse .agents/plugins --sparse plugins/codex-model-effort-router
codex plugin add model-effort-router@model-effort-router
```

**Claude Code** — 이 저장소의 Claude marketplace를 등록하고 플러그인을 설치한 뒤 새 세션을 시작합니다.

```sh
claude plugin marketplace add kyungpyokim/model-effort-router
claude plugin install model-effort-router@model-effort-router
```

**Antigravity CLI** — 로컬 플러그인 디렉터리를 설치합니다.

```sh
agy plugin install ./plugins/antigravity-model-effort-router
```

**OpenCode** — 저장소에서 플러그인 의존성을 설치하고 프로젝트의 `opencode.json`에 경로를 추가합니다.

```sh
cd plugins/opencode-model-effort-router
bun install --frozen-lockfile
```

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugins": ["./plugins/opencode-model-effort-router"]
}
```

모든 호스트 통합은 기본 모델 추천과 설정된 대안 후보를 안내할 수 있습니다. Codex·Claude·Antigravity는 hook 안내에, OpenCode는 `model_options`에 후보를 표시합니다. 이 후보는 현재 모델을 바꾸거나 자동 재시도를 실행하지 않습니다. 호스트별 제약은 각 플러그인 README를 참고하십시오.

모든 호스트 통합은 모델·effort 추천만 제공합니다. Marketplace 플러그인 설치는 공유 runtime을 설치하거나 업데이트하지 않습니다. runtime을 업데이트할 때는 이 checkout에서 `python3 scripts/install_core.py`를 다시 실행하십시오. 호스트별 자세한 내용은 [Codex 플러그인 가이드](https://developers.openai.com/plugins/build/plugins), [Claude Code marketplace 가이드](https://code.claude.com/docs/en/plugin-marketplaces), [Antigravity 플러그인 가이드](https://antigravity.google/docs/plugins/), [OpenCode 플러그인 가이드](https://dev.opencode.ai/docs/plugins/)를 참고하십시오.

## 업데이트와 릴리스

플러그인 업데이트는 `version`이 바뀌어야 설치한 사용자에게 전달되고, marketplace 설치는 공유 runtime을 건드리지 않습니다. 변경이 `main`에 머지된 뒤에는 명령 하나로 이 기기의 모든 설치를 갱신합니다.

```sh
git checkout main && git pull
scripts/deploy.sh                 # 전체 대상
scripts/deploy.sh claude codex    # 대상 선택: core|claude|codex|antigravity|opencode
```

| 대상 | 실행 내용 | 기준 소스 |
|---|---|---|
| `core` | `scripts/install_core.py`와 `--check` | 이 checkout |
| `claude` | `claude plugin marketplace update`, `claude plugin update` | GitHub `main` |
| `codex` | `codex plugin marketplace upgrade`, `codex plugin add` | GitHub `main` |
| `antigravity` | `agy plugin validate`, `agy plugin install` | 이 checkout |
| `opencode` | `bun install --frozen-lockfile` (`opencode.json`이 이미 이 checkout을 가리킴) | 이 checkout |

CLI가 설치되어 있지 않은 대상은 건너뜁니다. checkout이 `origin/main`이 아니면 경고하고, 실패한 단계가 있어도 끝까지 진행한 뒤 실패한 명령을 나열하며 0이 아닌 코드로 종료합니다. 끝나면 각 호스트에서 새 세션을 시작해야 hook이 다시 로드됩니다.

릴리스 순서:

1. Claude·Codex `plugin.json`, OpenCode `package.json`·`package-lock.json`의 `version`과 `tests/test_opencode_plugin.py`, `tests/test_plugin_bundle.py`의 버전 단언을 올립니다.
2. `main`에 머지하고 `main` CI가 통과할 때까지 기다립니다.
3. 머지 커밋에 `model-effort-router--vX.Y.Z` 태그를 달고 `Model Effort Router X.Y.Z` 제목으로 GitHub Release를 발행합니다(`gh release create`).
4. `scripts/deploy.sh`를 실행합니다.

## 라우팅 계약

MER는 개발 요청을 3가지 독립된 축(**역할(role)**, **노력 수준(effort)**, **작업 체급(tier)**)으로 분류합니다(`confidence`와 `reason_code`는 선택 사항):

- **역할 (Role)**: `implementation`, `fix`, `lint`, `test`, `plan`, `design`, `review`, `analysis`. 앞의 네 역할은 실행(execution) 모델 레인을 사용하고, 나머지는 추론(reasoning) 모델 레인을 사용합니다.
- **노력 수준 (Effort)**: `low`, `medium`, `high`, `xhigh`, `max`. 독립적인 위험 감지는 안전 민감 검토/설계 요청을 최소 `high`까지 올릴 수 있지만, 역할이나 모델 레인은 변경하지 않습니다. 모델 레인의 `efforts`에 `max`가 없고 `ultra`가 정의되어 있으면(`xhigh`에서 바로 `ultra`로 넘어가는 모델), 분류기의 `max`는 `ultra`로 자동 매핑됩니다.
- **작업 체급 (Tier)**: `economy`, `balanced`, `frontier`. 모델의 지능 체급(지능 수준/규모)을 추론 노력 수준(effort)과 독립적으로 분리하여 판단합니다:
  - `economy`: 단일 함수/클래스/모듈 구현, 국소적인 버그 수정, 단위 테스트, 일상적 리팩터링 등 빠르고 가벼운 경제형 모델(Luna, Haiku 5.5, Flash 등)이 적절한 reasoning effort와 결합하여 잘 처리할 수 있는 자기완결적 작업.
  - `balanced`: 다중 모듈 및 컴포넌트 간 기능 개발, 서브시스템 간 상호작용, 상태 관리, 아키텍처 가이드 기반 변경 작업(Terra, Sonnet 5.5 등).
  - `frontier`: 시스템 전반의 아키텍처 설계, 미묘한 크로스 시스템 추론, 동시성/보안/데이터 무결성이 결부된 미션 크리티컬 의사결정(Sol, Opus 5.5, Argon 등).

### 호스트별 기본 모델 매핑

| 호스트 | Economy | Balanced | Frontier |
|---|---|---|---|
| **Codex** | `gpt-6-luna` | `gpt-6.1-terra` | `gpt-6.1-sol` |
| **Claude** | `claude-haiku-5-5` | `claude-sonnet-5-5` | `claude-opus-5-5` |
| **Antigravity** | `gemini-3.8-flash` | `claude-sonnet-5-5` | `gemini-4-argon` *(대안: `claude-opus-5-5`)* |
| **OpenCode** | `opencode/mimo-v2.6-flash-free` | `opencode-go/glm-5.3` | `opencode/nemotron-3-ultra-free` *(대안: `opencode-go/glm-5.3`, `opencode-go/kimi-k3`, `opencode-go/grok-4.7`)* |

각 호스트/레인에서 `primary`, 선택적 `alternatives`, 지원 `efforts`, 그리고 선택적 `tiers` 매핑을 설정할 수 있습니다. `primary`를 추천하고 `alternatives`를 사용자가 고를 후보로 표시합니다. 이전 설정 호환성을 위해 모델별 `fallback` 값은 읽지만 더는 사용하지 않습니다. 예시:

```json
{
  "models": {
    "codex": {
      "execution": {
        "primary": "gpt-6-luna",
        "tiers": {
          "economy": "gpt-6-luna",
          "balanced": "gpt-6.1-terra",
          "frontier": "gpt-6.1-sol"
        },
        "alternatives": ["gpt-6-astra"],
        "efforts": ["low", "medium", "high", "xhigh", "max"]
      },
      "reasoning": {
        "primary": "gpt-6.1-sol",
        "tiers": {
          "economy": "gpt-6-luna",
          "balanced": "gpt-6.1-terra",
          "frontier": "gpt-6.1-sol"
        },
        "alternatives": ["gpt-6-astra"],
        "efforts": ["low", "medium", "high", "xhigh", "max"]
      }
    }
  }
}
```

lane의 `efforts`에 `max`는 없고 `ultra`만 있으면(선택기가 `xhigh` 다음에 바로 `ultra`인 모델) 분류기의 `max`를 `ultra`로 적용합니다. `ultra`는 작업 자동 위임이 더해지므로 토큰이 더 들 수 있습니다.

예시 모델 ID는 각 호스트에서 사용할 수 있는 모델로 바꾸십시오. OpenCode는 `model_options`를 반환하고, 다른 hook은 안내문에 alternatives를 표시합니다. 대안 후보는 추천에만 사용되며 자동 모델 전환을 일으키지 않습니다. 분류기 provider는 설정된 다음 분류기로 넘어갈 수 있습니다. 모두 실패하면 CLI 라우팅은 오류를 반환하고 hook은 fail open으로 사용자 요청을 막지 않습니다.

## 분류기 backend 설정

분류기 backend는 요청의 role과 effort를 판정합니다. 추천 호스트 모델을 제공하는 `models.<host>`와는 별개입니다. 내장 분류기 기본값은 fallback이 없는 `subscription`입니다. TypeSafe Jev를 role/effort 분류기의 주 backend로 사용하려면 `difficulty.backend`를 `jev`로 설정합니다.

```json
{
  "difficulty": {"backend": "jev", "fallback": "subscription", "timeout_s": 10}
}
```

`backend: jev`이면 호스트가 만든 메시지를 제외한 모든 프롬프트가 Jev API로 전송되어 라우팅 대상 여부(`route`/`no_route`), role, effort를 판정합니다. 키워드 사전 필터는 없으며, 설정된 분류기가 공백이 아닌 모든 프롬프트를 판정합니다(Jev가 아닌 backend는 항상 route로 보므로 잡담도 분류기를 한 번 호출합니다).

`fallback`은 목록도 받으며 `backend` 다음에 순서대로 시도합니다. 예: `"fallback": ["openai_decisions", "nimble"]`. 전체 chain이 hook의 30초 제한 안에 들어오도록 backend별 `timeout_s`가 제한됩니다(backend 1~2개는 각 12초, 3개는 각 8초).

**세션 컨텍스트 (Claude, Codex hook).** "진행"처럼 짧은 후속 요청도 이어지는 작업을 기준으로 분류할 수 있도록, hook은 현재 프롬프트와 함께 세션 요약과 최근 user/assistant turn(텍스트만, 도구 출력 제외)을 Jev에 전송합니다. 요약은 호스트 자신의 CLI(`claude -p` Haiku, `codex exec` 경제 모델은 shell과 exec 도구를 끈 상태로 실행, 텍스트는 stdin 전달)가 백그라운드에서 만들어 state 디렉터리에 저장하고(14일간 쓰지 않은 요약 파일은 삭제), 한 turn 늦을 수 있어 가장 최근 turn은 원문 그대로 보냅니다. hook은 요약 작업을 기다리지 않습니다. 저장소 또는 사용자 설정에서 `{"context": {"enabled": false}}`로 끌 수 있고, `context.max_chars`(기본 6000)가 요약과 최근 turn의 크기를 제한합니다. `context.enabled: false`이면 현재 프롬프트만 전송됩니다. 백그라운드 요약은 독립 실행 `claude` CLI가 로그인되어 있어야 합니다(`claude auth login`). Claude 데스크톱 앱 세션의 로그인은 CLI에 공유되지 않으며, 로그인되지 않으면 요약을 건너뛰고 오류 이벤트만 기록합니다. Codex 요약에는 `codex` CLI 로그인(`codex login`)이 필요합니다.

Codex 제한 사항: Codex 0.160.1에서는 해당 도구를 끈 `codex exec`가 직접 지시, 프롬프트 주입, `functions.exec` / `spawn_agent` 우회 시도 모두에서 canary 파일을 읽지 못했고, 플래그 없이 실행하면 읽었습니다. 이는 그 버전에 대한 행동상의 증거일 뿐 보장은 아닙니다. 다른 Codex 버전에서는 Codex 요약을 건너뛰고(오류 이벤트 기록) Codex 분류기에는 도구 비활성화 플래그와 세션 컨텍스트를 모두 넣지 않습니다. `--ignore-user-config`를 써도 전역 `~/.codex/AGENTS.md`는 계속 로드됩니다(확인: 간단한 프롬프트에도 입력 토큰 약 26k, `-c project_doc_max_bytes=0`으로도 해결되지 않음). 따라서 사용자 수준 Codex 지침은 모든 Codex 분류기·요약 호출에 토큰을 더합니다.

Jev는 기본적으로 `jev-latest` 모델을 사용합니다. API 키는 저장소 설정이 아닌 `~/.config/model-effort-router/config.json`에 저장합니다.

```json
{
  "jev": {"api_key": "your-typesafe-api-key"}
}
```

다른 Jev 모델을 쓰려면 선택 항목 `"model"`을 추가하세요(예: `{"jev": {"api_key": "...", "model": "jev-1.13-free"}}`). 이 값은 `MER_JEV_MODEL`보다, `MER_JEV_MODEL`은 `jev-latest`보다 우선합니다.

설정된 주 backend를 먼저 호출하고, 실패한 경우에만 fallback을 호출합니다.

OpenAI Decisions API도 선택형 `openai_decisions` backend로 사용할 수 있습니다(기본 모델 `gpt-6-luna`).

```json
{"difficulty": {"backend": "openai_decisions", "fallback": "subscription", "timeout_s": 10}}
```

`OPENAI_API_KEY` 환경변수를 설정하거나, 키를 저장소가 아닌 전역 `~/.config/model-effort-router/config.json`에 저장합니다.

```json
{"openai": {"api_key": "your-openai-api-key"}}
```

Nimble을 로컬 분류기로 사용하려면 Ollama를 설치하고 로컬 서버가 실행 중인지 확인한 뒤 모델을 받아옵니다.

```sh
ollama pull nimble
```

Nimble은 기본적으로 API 키 없이 `http://127.0.0.1:11434/v1/systemone`의 `nimble` 모델을 사용합니다. `difficulty.backend`를 `nimble`로 선택합니다. 예시:

```json
{
  "difficulty": {
    "backend": "nimble",
    "fallback": "jev",
    "timeout_s": 10,
    "nimble": {
      "model": "nimble",
      "url": "http://127.0.0.1:11434/v1/systemone"
    }
  }
}
```

위 `difficulty` 객체를 저장소 루트의 `.model-effort-router.json` 또는 `~/.config/model-effort-router/config.json`에 추가합니다. `difficulty.nimble.model`과 `.url`은 기본값을 재정의합니다. Nimble URL은 HTTP(S)를 사용하고 `localhost`, `127.0.0.1`, `::1`을 가리켜야 합니다. MER는 loopback이 아닌 URL을 거부하므로 Nimble 요청은 기기 안에서 처리됩니다. 위 예시에서는 Nimble이 실패하면 작업 내용이 TypeSafe의 호스팅 Jev로 전송됩니다. 이 fallback을 사용하려면 Jev API 키를 설정하십시오.

Laya를 로컬 분류기로 사용하려면 serving 추가 기능을 설치하고 서버를 loopback에 바인딩합니다.

```sh
python -m pip install 'laya[serve]'
LAYA_HOST=127.0.0.1 laya-serve
```

`.model-effort-router.json` 또는 전역 설정에서 선택합니다.

```json
{"difficulty": {"backend": "laya", "laya": {"model": "laya", "url": "http://127.0.0.1:8000/v1/systemone"}}}
```

Laya는 기본적으로 `http://127.0.0.1:8000/v1/systemone`의 `laya` 모델을 사용합니다. `difficulty.backend: "laya"`로 선택할 수 있습니다. `difficulty.laya.model`과 `.url`이 기본값을 재정의하고, 설정에 값이 없으면 `MER_LAYA_MODEL`, `MER_LAYA_URL` 환경 변수를 사용합니다. URL은 HTTP(S)이며 `localhost`, `127.0.0.1`, `::1` 중 하나를 가리켜야 합니다. 로컬 서버에 bearer 인증이 필요한 경우에만 `MER_LAYA_API_KEY`를 설정하십시오. 기본 `laya` 모델 alias는 English 체크포인트로 연결됩니다. 실패 후 다른 분류기를 사용하려면 `fallback`을 별도로 설정하십시오. 서버 API는 [Laya HTTP API 문서](https://nandhakishorm.github.io/laya/http-api/)를 참고하십시오.

### 분류기 성능

합성 코퍼스 v3 150건에서 측정한 role/effort 라벨 일치율입니다.

| Backend | Role | Effort | Role + effort |
|---|---:|---:|---:|
| Jev (`jev-latest`) | 141/150 (94.0%) | 119/150 (79.3%) | 111/150 (74.0%) |
| Nimble | 124/150 (82.7%) | 101/150 (67.3%) | 85/150 (56.7%) |
| Laya (`english`) | 90/150 (60.0%) | 38/150 (25.3%) | 30/150 (20.0%) |
| Laya (`laya:322m-multilingual-mlx-fp16`, Ollama MLX) | 56/150 (37.3%) | 30/150 (20.0%) | 11/150 (7.3%) |
| OpenAI Decisions API (`gpt-6-luna`) | 136/150 (90.7%) | 119/150 (79.3%) | 107/150 (71.3%) |

Decisions API는 API 엔드포인트이고 `gpt-6-luna`는 해당 API에서 사용하는 모델입니다. 이 코퍼스에서는 Jev가 가장 높은 일치율을 기록했습니다. 모든 결과는 같은 기존 평가 케이스와 다수결 라벨을 사용하므로 독립적인 실제 사용자 정확도가 아닙니다. 영어 Laya와 다국어 Laya는 checkpoint, serving runtime, 질문 지시문이 달라 점수 차이를 다국어 지원 효과 하나로 분리할 수 없습니다. Nimble은 로컬 추론에 사용할 수 있으며, 요청이 기기 밖으로 나가지 않게 하려면 fallback을 `none`으로 설정하십시오. 자세한 내용은 [평가 인덱스](docs/evaluation/README.md), [영어 Laya 측정](docs/evaluation/laya-20261008.md), [다국어 Laya 측정](docs/evaluation/laya-multilingual-20261008.md), [Decisions API 측정](docs/evaluation/openai-decisions-20261007.md)을 참고하십시오.

## 사용법

```sh
python3 <plugin>/bin/mer route --host codex --json 'Review the authentication changes'
python3 <plugin>/bin/mer route --host codex --role implementation --effort high --json 'Implement the approved design'
python3 <plugin>/bin/mer report --since 12h --limit 10
python3 <plugin>/bin/mer on                        # 전역 라우터 활성화 (mode: auto)
python3 <plugin>/bin/mer off                       # 전역 라우터 비활성화 (mode: off, 바이패스)
python3 <plugin>/bin/mer status                    # 현재 활성 상태 및 설정 소스 확인
python3 <plugin>/bin/mer off --local               # 현재 저장소 로컬에서만 비활성화
```

`mer route`는 요청의 role, effort, tier를 분류하고 호스트 모델에 매핑합니다. 명시적인 라우팅을 지정하려면 `--role`과 `--effort`(선택적으로 `--tier`)를 함께 제공해야 합니다. 호스트 채팅 내에서 `/router role=<role> effort=<effort> tier=<tier>` 형식으로 직접 오버라이드할 수도 있습니다. MER는 작업자 실행, 검증 루프, 리뷰 또는 수정 절차를 실행하지 않습니다. 기존 스크립트 호환성을 위해 `mer run`과 `mer chat`은 종료 코드 2와 함께 `mer route` 사용 안내를 반환합니다. 오래된 로그의 `run` 항목은 `mer report`에서 계속 읽을 수 있습니다.

`mer on`과 `mer off`는 라우터를 전역 또는 로컬(`--local`)로 즉시 켜고 끕니다. 비활성화(`mode: "off"`) 시 분류기 호출과 프롬프트 조언 주입을 완전히 건너뛰고(bypass) 호스트 기본 모델로 직접 동작합니다. `mer status`는 현재 라우터 활성 여부(`ON`/`OFF`), 적용 모드, 설정 출처를 출력합니다. Antigravity, Claude Code, Codex 플러그인은 `router` 스킬을 통해 채팅창에서 `/router on` 및 `/router off` 슬래시 명령도 지원합니다.

OpenCode의 `mer` 도구도 같은 모델·effort 추천을 반환하며, `mer_report`는 로그를 요약합니다. 호스트 hook은 추천을 추가할 뿐 활성 모델/effort를 변경하지 않습니다. Codex·Claude 데스크톱 앱은 hook 출력을 표시하지 않으므로, hook 조언은 Main이 첫 답변 줄에 추천을 적도록 요청합니다.

호스트의 의도한 작업 흐름은 **작업 지시 → MER 모델·effort 추천 → 호스트 작업 → 호스트 리뷰 → 호스트 수정**입니다. MER는 추천에서 종료하며 worker 실행, 리뷰, 수정, 검증 루프를 시작하지 않습니다.

## 설정

설정은 저장소 루트의 `.model-effort-router.json` 또는 `~/.config/model-effort-router/config.json`에 JSON으로 작성합니다. 저장소 값이 사용자 값을 덮어씁니다. 기존 사용자 파일은 다시 작성하지 않습니다. 예시:

```json
{
  "router": {"mode": "auto"},
  "difficulty": {"backend": "jev", "timeout_s": 10},
  "models": {
    "codex": {
      "execution": {"primary": "gpt-6-luna", "alternatives": ["gpt-6-astra"], "efforts": ["low", "medium", "high", "xhigh"]},
      "reasoning": {"primary": "gpt-6.1-sol", "alternatives": ["gpt-6-astra"], "efforts": ["low", "medium", "high", "xhigh"]}
    },
    "claude": {
      "execution": {"primary": "claude-sonnet-5-5", "alternatives": ["claude-fable-5-1"], "efforts": ["low", "medium", "high", "xhigh"]},
      "reasoning": {"primary": "claude-opus-5-5", "alternatives": ["claude-fable-5-1"], "efforts": ["low", "medium", "high", "xhigh"]}
    },
    "antigravity": {
      "execution": {"primary": "gemini-3.8-flash", "alternatives": ["claude-sonnet-5-5"], "efforts": ["medium", "high"]},
      "reasoning": {"primary": "gemini-4-argon", "alternatives": ["claude-opus-5-5"], "efforts": ["medium", "high"]}
    },
    "opencode": {
      "execution": {"primary": "opencode/mimo-v2.6-flash-free", "efforts": ["low", "medium", "high", "xhigh"]},
      "reasoning": {"primary": "opencode/nemotron-3-ultra-free", "alternatives": ["opencode-go/glm-5.3", "opencode-go/kimi-k3", "opencode-go/grok-4.7"], "efforts": ["low", "medium", "high", "xhigh"]}
    }
  }
}
```

Legacy L1-L5, session, escalation 및 `nimble_jev` 설정은 마이그레이션 안내와 함께 거부됩니다. 이전 설정 오버라이드는 `/router role=<role> effort=<effort> tier=<tier>`로 바꾸고, 이전 Main-session 라우팅 명령은 `mer route`로 바꾸십시오. `nimble_jev`는 제거되었으므로 `nimble`과 `jev` 같은 별도의 classifier fallback을 설정하십시오.

Jev 인증 정보는 전역 사용자 설정에만 둘 수 있습니다. 자세한 방법은 [분류기 backend 설정](#분류기-backend-설정)을 참고하십시오. 저장소 설정에는 이 인증 정보를 둘 수 없습니다.

### 실험: policy 모드

`router.mode = "policy"`는 분류기를 건너뜁니다. `UserPromptSubmit` hook은 정적 모델 맵(execution/reasoning lane과 지원 effort)을 모델 선정 참고 정보로 주입합니다. 비어 있지 않은 prompt마다 정책을 주입하며 모델 호출은 하지 않습니다. Codex와 Claude에서만 동작하며 다른 host는 아무 안내도 하지 않습니다.

- 활성화: 전역 사용자 설정에 `{"router": {"mode": "policy"}}`를 넣거나 프롬프트를 `/router policy`로 시작합니다. `"mode": "auto"`(기본값)로 되돌리면 해제됩니다. 명시적 `/router role=<role> effort=<effort>`는 기존 동작을 유지합니다.
- `auto`와 비교하기 위한 A/B 실험이며, 비교 후 진 쪽 모드는 제거될 예정입니다.
- 워크플로우 로그로 비교합니다: `python3 scripts/compare_modes.py [--since <unix ts>]`가 모드와 host별 route 수, Subagent 상관관계 수, hook 지연 중앙값, 분류기 토큰을 출력합니다.

## 워크플로우 로그

세션마다 `~/.local/state/model-effort-router/<session>-<hash>.log.jsonl`에 기록됩니다(`MER_STATE_DIR`로 변경 가능). 이벤트에는 `route`(결정과 advice action), 호스트가 보고한 `subagent_start`/`subagent_stop`, 과거 `run`, `context_refresh`, 고정 코드 `error`가 포함될 수 있습니다. 현재 MER는 `run` 이벤트를 새로 만들지 않으며 예전 로그는 호환성을 위해 읽습니다. 프롬프트와 Subagent 출력은 저장하지 않습니다.

- `subagent_start`에는 세션의 마지막 `route`를 기준으로 한 `correlation.expected`와 `correlation.matched`가 붙습니다. 현재 route는 `selection_only`로 표시됩니다. Codex는 호스트가 보고한 Subagent 모델과 추천 모델을 비교할 수 있습니다(`matched_on: ["model"]`). Claude lifecycle payload에는 모델이 없어 현재 route에서는 비교하지 않습니다(`matched_on: []`). MER는 호스트 이벤트를 기록할 뿐 Subagent를 실행하거나 지시하지 않습니다. 과거 `selection_only` 없는 route는 Claude agent type 비교를 계속 지원합니다. effort는 검증하지 않습니다.
- `subagent_stop`은 같은 `agent_id`의 `subagent_start`가 가진 `correlation`을 복사하며, 없으면 `null`입니다.
- Subagent 이벤트는 Codex의 `turn_id`를 `agent_turn_id`로 기록합니다. 이는 child turn이며 route의 `turn_id`와 다릅니다.
- 분류기 fallback: 분류기가 실패해 라우팅이 fallback으로 넘어가면 `route` 이벤트에 `classifier_causes`(예: `["jev:HTTP 503"]`, backend 이름, 오류 타입, HTTP 상태 코드만 기록하며 오류 메시지는 기록하지 않음)가 남고 `no_route`와 모든 분류기가 실패한 경우에도 기록됩니다. hook은 `[model-effort-router] classifier fallback: jev failed (HTTP 503) → classified by openai_decisions`를 표시하고, 모든 분류기가 실패하면 `classifier failed: ...; no routing advice this turn.`을 표시합니다. Codex와 Claude 데스크톱 앱은 hook 메시지를 표시하지 않으므로 advice가 Main에게 사용자에게 알리라고도 지시합니다.
- hook은 라우팅 추천만 제공하며 활성 모델이나 effort를 바꾸지 않습니다. route 로그에는 추천 프로필과 가능한 경우 Main 모델이 기록됩니다. Codex role 설정(`.codex/agents/*.toml`)은 추천과 다르게 설정할 수 있습니다. 호스트가 보고한 Subagent 모델을 비교할 수 있지만, effort를 검증하거나 실행을 제어하지는 않습니다.
- 한계: 마지막 route는 로그 끝 64KB 안에서만 찾으며, 라우팅이 `off`인 프롬프트는 `route` 이벤트를 쓰지 않으므로 그 뒤 시작한 Subagent는 이전에 기록된 route와 비교됩니다.

```bash
jq -c 'select(.event|test("route|subagent|run")) | {ts,event,action:.advice.action,model:(.model // .advice.routed_model),matched:.correlation.matched}' ~/.local/state/model-effort-router/<session>-*.log.jsonl
```

### 리포트

`mer report`는 이 로그를 요약합니다. 최근 `route`, 과거 `run`, `subagent` 행(모델, effort, 역할, 분류기, 추천 동작, 알려진 경우 Main의 모델과 effort를 `main=<model>/<effort>`로, 토큰 사용량)을 나열한 뒤, 조건에 맞는 전체 세션을 합산합니다. 합산 항목은 라우팅된 `(model, effort)` 조합, 모델 추천 상태, 가능한 경우 route 대비 Subagent의 `matched`/`mismatched`/`unverified`, 분류기 상태(에러, 폴백, 지연 시간 평균과 p95, 실패 원인), 분류기 token입니다. 과거 run 행은 route-only 전의 실행 기록이며 호환성을 위해 계속 표시됩니다.

- 옵션: `--session <세션 ID 앞부분>`, `--since <n>m|h|d`(예: `12h`), `--limit <n>`(나열할 행 수, 기본 20, `0`이면 요약만 출력).
- 토큰은 `route`(분류기 호출)에 기록되며, 과거 `run` 행에는 worker token이 남아 있을 수 있습니다. Main과 Subagent 턴은 로그에 남지 않아 그 토큰은 표시되지 않습니다.
- Claude, Codex, Antigravity는 `classify`, `router`, `report` 스킬을 제공합니다. OpenCode는 `mer_report` 도구를 제공하며, `mer route --session <id>`로 세션별 route를 로그에 남깁니다.

## 버전별 변경사항 (Changelog)

### [v0.18.0] - 2026-10-27
- **Jev 티어 분류 기준 재조정**: `jev_questions.json`의 판정 기준을 정교화하여 작업 규모와 체급을 명확히 구분:
  - `economy`: 단일 함수/모듈, 버그 수정, 단위 테스트, 일상적 리팩터링 등 가벼운 경제형 모델(Luna, Haiku 5.5, Flash 등)이 적절한 reasoning effort와 결합하여 충분히 해결 가능한 국소적 작업.
  - `balanced`: 다중 모듈 또는 컴포넌트 간 기능 개발, 비자명한 상태 관리, 서브시스템 간 상호작용 등 균형 잡힌 모델(Terra, Sonnet 5.5 등)이 필요한 작업.
  - `frontier`: 시스템 전반의 아키텍처 설계, 심층적인 크로스 시스템 추론, 동시성/보안/데이터 손실 방지가 직결된 핵심 의사결정(Sol, Opus 5.5, Argon 등).

### [v0.17.0] - 2026-10-27
- **라우터 모드 토글 명령어 및 스킬 추가**:
  - `mer on`, `mer off`, `mer status`, `mer mode [on|off|auto|status]` CLI 명령어 지원 (`--local` 옵션으로 저장소 로컬 `.model-effort-router.json`에만 적용 가능).
  - Antigravity, Claude Code, Codex 플러그인에 `router` 스킬 추가 (`/router on`, `/router off` 슬래시 커맨드 지원).
  - `mode: "off"` 시 분류기 API 호출과 훅 조언 주입을 최우선으로 바이패스하여 지연 시간과 불필요한 토큰 소모를 방지하고 호스트 기본 모델로 즉시 복귀.

### [v0.16.2] - 2026-10-26
- **작업 체급(`tier`)과 추론 깊이(`effort`)의 분리**:
  - 3개 독립 축 분류 체계 도입: `role`(역할), `effort`(`low`..`ultra` 추론 깊이), `tier`(`economy`, `balanced`, `frontier` 모델 체급).
  - 호스트별 기본 모델 티어 매핑 정립:
    - **Codex**: `gpt-6-luna` (economy), `gpt-6.1-terra` (balanced), `gpt-6.1-sol` (frontier).
    - **Claude**: `claude-haiku-5-5` (economy), `claude-sonnet-5-5` (balanced), `claude-opus-5-5` (frontier).
    - **Antigravity**: `gemini-3.8-flash` (economy), `claude-sonnet-5-5` (balanced), `gemini-4-argon` (frontier, 대안: `claude-opus-5-5`).
    - **OpenCode**: `opencode/mimo-v2.6-flash-free` (economy), `opencode-go/glm-5.3` (balanced), `opencode/nemotron-3-ultra-free` (frontier).
  - Jev(`jev_questions.json`) 및 Laya(`laya_instructions.json`) 분류기에 tier 판별 질문 추가.
  - 설정의 `models.<host>.<lane>.tiers` 매핑 및 채팅창 오버라이드 `/router ... tier=<tier>` 지원.

### [v0.16.1] - 2026-10-26
- **Ultra effort 자동 매핑**: `max` effort를 지원하지 않고 `ultra`를 지원하는 모델/레인에서 분류기의 `max` 요청을 `ultra`로 자동 매핑. 설정의 `efforts` 배열에 `ultra` 허용.

### [v0.16.0] - 2026-10-26
- **Codex balanced 모델 업데이트**: Codex balanced 티어 기본 모델로 `gpt-6.1-terra` 추가 및 지원 effort 등록.

### [v0.15.0] - 2026-10-19
- **데스크톱 UI 조언 노출 복원**: Codex 데스크톱 UI 및 Claude 데스크톱 앱에서 Main 첫 답변 줄에 추천 태그를 출력하도록 가이드 복원 (`advice_reply_tag.txt`).
- 응답 태그 프롬프트를 `prompts/` 디렉터리로 분리.

### [v0.14.0] - 2026-10-19
- **MER 역할을 라우팅 추천 전용으로 단순화**:
  - MER의 책임을 모델/effort/tier 추천으로 집중하고 작업 실행, 테스트 루프, 리뷰, 수정은 호스트가 전담하도록 위임.
  - `implementation` 및 `fix` 요청 시 작업 완료 후 독립 리뷰를 요청하도록 조언(advice) 안내 메시지 추가.
  - 프롬프트 텍스트를 `model_effort_router/prompts/` 디렉터리 내 개별 파일로 분리.

### [v0.13.4] - 2026-10-12
- **워크플로우 로그 및 진단 강화**:
  - `route`, `subagent_start`/`stop`, `context_refresh`, `error` 이벤트 구조화.
  - Jev 에러 디버그 진단 로그 강화: HTTP 상태 코드, 단계 정보 기록, 응답 발췌문 길이 제한(240자) 및 민감 정보/자격 증명 마스킹.
  - `mer report`의 이벤트 출력 및 요약 처리 모듈화.

### [v0.13.3] - 2026-10-12
- **답변 첫 줄 태그에 Main의 effort 표기**: `[main: <model> · effort <effort>]` 형태로 현재 모델과 effort 상태 노출.
- 호스트 Main 모델 및 effort 판별 분기를 host별 reader 레지스트리(`READERS`)로 리팩터링.
- `scripts/deploy.sh`에 Antigravity 설치본 `diff` 검증 추가.

### [v0.13.2] - 2026-10-12
- **리포트 상세 통계 추가**: `mer report`에 모델-effort 분포, 분류기 토큰 소모량, Subagent 생애주기 상관관계 통계 추가.
- 세션 컨텍스트 백그라운드 요약(보존 기간 14일) 도입.

### [v0.12.1] - 2026-10-08
- **플러그인 버전 동기화**: Codex, Claude, OpenCode 플러그인 버전 `0.12.1` 정렬 및 안정화.

### [v0.12.0] - 2026-10-08
- **`no_route` 및 프로젝트 타깃 개선**: 잡담 및 비개발 요청을 Main 에이전트로 원활하게 안내. Jev 프로젝트 결과물 판정 정확도 개선.

### [v0.11.2] - 2026-10-07
- **통일된 라우팅 표시 포맷**: 모든 호스트 hook 표면에 `[model-effort-router] model: <model> · effort: <effort>` 형식의 표준화된 배너 적용.

### [v0.11.1] - 2026-10-07
- **OpenCode UI 배너**: OpenCode 라우팅 배너 UI 표시 및 TypeScript 타입 검사 보강.

### [v0.11.0] - 2026-10-07
- **Laya 분류기 연동**: 로컬 Laya 분류기 백엔드(`english`, `multilingual`) 및 벤치마크 평가 추가. 호스트 턴 훅에서 선택된 모델과 effort를 명시적으로 표시.

### [v0.10.0] - 2026-10-07
- **세션 맥락 요약 도입**: Claude 및 Codex 훅에서 백그라운드 세션 맥락 요약을 전송하여 "계속해줘" 등 짧은 후속 지시도 앞선 작업의 역할과 effort를 상속하도록 개선.

### [v0.9.0] - 2026-10-07
- **OpenCode 프롬프트 훅 및 Max effort**: OpenCode 자동 프롬프트 분류 훅 추가 및 전 호스트 대상 `max` effort 라우팅 지원.

### [v0.8.1] - 2026-10-07
- **OpenCode v2 플러그인 전환**: OpenCode v2 플러그인 사양으로 전환하고 `mer` 도구 등록.

### [v0.8.0] - 2026-10-07
- **OpenAI Decisions API 백엔드**: 선택적 `openai_decisions` 분류기 백엔드(`gpt-6-luna`) 추가.
- 초기 OpenCode 플러그인 지원 및 대안 모델(`alternatives`) 설정 도입.

### [v0.7.0] - 2026-10-06
- **공유 코어 아키텍처 리팩터링**: 각 플러그인에 흩어져 있던 코어 사본을 제거하고 단일 `model_effort_router` 패키지로 통합.
- 역할(role) 및 노력 수준(effort) 중심 라우팅 계약 확립. Jev 및 Nimble 분류기 백엔드 지원.
- `classify`와 `review` 스킬 분리. 한국어 문서(`README.ko.md`) 추가.

## Runtime 개발

`model_effort_router/`가 공유 runtime source입니다. Plugin에는 host integration만 포함됩니다. 개발 시 `MER_CORE_PATH="$PWD"`를 사용하십시오. 다음 명령으로 설치하고 검증합니다:

```sh
python3 scripts/install_core.py
python3 scripts/install_core.py --check
MER_CORE_PATH="$PWD" python3 -m unittest discover -s tests
```

`pre-commit` CLI를 설치하고 `npm --prefix plugins/opencode-model-effort-router ci`를
실행한 뒤 `git config core.hooksPath .githooks`로 저장소 훅을 활성화하십시오.
Python 파일에는 Ruff를, TypeScript 파일에는 OpenCode
패키지의 ESLint와 Prettier를 실행합니다.

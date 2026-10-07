# Model Effort Router

영문판: [README.md](README.md)

MER는 개발 요청을 **역할 + 노력 수준**으로 분류하고, 해당 조합을 호스트 모델에 매핑하며, 외부 worker 요청을 실행할 수 있습니다. Main은 대화 컨텍스트를 유지하고, 필요한 단계를 결정하며, 호스트 네이티브 Subagent를 호출하는 일을 계속 담당합니다. MER는 현재 Codex 턴을 변경하지 않습니다. Worker 실행은 검증 기반 노력 수준 승격을 선택할 수 있습니다.

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

Antigravity와 OpenCode는 분류와 조언만 지원하며 worker 실행은 지원하지 않습니다. Marketplace 플러그인 설치는 공유 runtime을 설치하거나 업데이트하지 않습니다. runtime을 업데이트할 때는 이 checkout에서 `python3 scripts/install_core.py`를 다시 실행하십시오. 호스트별 자세한 내용은 [Codex 플러그인 가이드](https://developers.openai.com/plugins/build/plugins), [Claude Code marketplace 가이드](https://code.claude.com/docs/en/plugin-marketplaces), [Antigravity 플러그인 가이드](https://antigravity.google/docs/plugins/), [OpenCode 플러그인 가이드](https://dev.opencode.ai/docs/plugins/)를 참고하십시오.

## 라우팅 계약

분류기는 `role`과 `effort`를 반환하며, `confidence`와 `reason_code`는 선택 사항입니다. 역할은 `implementation`, `fix`, `lint`, `test`, `plan`, `design`, `review`, `analysis`입니다. 앞의 네 역할은 실행 모델을 사용하고, 나머지는 추론 모델을 사용합니다. 노력 수준은 `low`, `medium`, `high`, `xhigh`입니다. 독립적인 위험 감지는 안전 민감 검토/설계 요청을 최소 `high`까지 올릴 수 있지만, 역할이나 모델 레인은 변경하지 않습니다.

기본값은 Codex 실행 `gpt-6-luna`·추론 `gpt-6.1-sol`, Claude 실행 `claude-sonnet-5-5`·추론 `claude-opus-5-5`, Antigravity 위임 프로필 `gemini-3.8-flash`, OpenCode 실행 조언 `opencode/mimo-v2.6-flash-free`·추론 조언 `opencode/nemotron-3-ultra-free`입니다. OpenCode 추론 후보는 `opencode-go/glm-5.3`, `opencode-go/kimi-k3`, `opencode-go/grok-4.7`입니다. 각 호스트/레인에서 `primary`, 선택적 `alternatives`, `fallback`, 지원 effort를 설정할 수 있습니다. `primary`를 추천하고 `alternatives`를 사용자가 고를 후보로 표시합니다. 예시:

```json
{
  "models": {
    "codex": {
      "execution": {
        "primary": "gpt-6-luna",
        "alternatives": ["gpt-6-astra", "provider/model-id"]
      },
      "reasoning": {
        "primary": "gpt-6.1-sol",
        "alternatives": ["gpt-6-astra", "provider/another-model"]
      }
    }
  }
}
```

예시 모델 ID는 각 호스트에서 사용할 수 있는 모델로 바꾸십시오. OpenCode는 `model_options`를 반환하고, 다른 hook은 안내문에 alternatives를 표시합니다. 대안 후보는 실행 재시도에 사용하지 않습니다. MER는 stderr만으로 실행 fallback을 추론하지 않으며 worker가 시작되었을 수 있는 경우 재시도하지 않습니다. 명시적인 사전 실행 불가 신호가 있을 때만 fallback을 허용합니다. 분류기 provider는 설정된 다음 분류기로 넘어갈 수 있습니다. 모두 실패하면 CLI 라우팅은 오류를 반환하고 hook은 fail open으로 사용자 요청을 막지 않습니다.

## 분류기 backend 설정

분류기 backend는 요청의 role과 effort를 판정합니다. worker model을 선택하는 `models.<host>`와는 별개입니다. 내장 분류기 기본값은 fallback이 없는 `subscription`입니다. TypeSafe Jev를 role/effort 분류기의 주 backend로 사용하려면 `difficulty.backend`를 `jev`로 설정합니다.

```json
{
  "difficulty": {"backend": "jev", "fallback": "subscription", "timeout_s": 10}
}
```

`backend: jev`이면 호스트가 만든 메시지를 제외한 모든 프롬프트가 Jev API로 전송되어 라우팅 대상 여부(`route`/`no_route`), role, effort를 판정합니다. 키워드 규칙은 Jev가 실패했을 때 fallback backend 호출 여부만 결정합니다.

**세션 컨텍스트 (Claude, Codex hook).** "진행"처럼 짧은 후속 요청도 이어지는 작업을 기준으로 분류할 수 있도록, hook은 현재 프롬프트와 함께 세션 요약과 최근 user/assistant turn(텍스트만, 도구 출력 제외)을 Jev에 전송합니다. 요약은 호스트 자신의 CLI(`claude -p` Haiku, `codex exec` 경제 모델은 shell과 exec 도구를 끈 상태로 실행, 텍스트는 stdin 전달)가 백그라운드에서 만들어 state 디렉터리에 저장하고(14일간 쓰지 않은 요약 파일은 삭제), 한 turn 늦을 수 있어 가장 최근 turn은 원문 그대로 보냅니다. hook은 요약 작업을 기다리지 않습니다. 저장소 또는 사용자 설정에서 `{"context": {"enabled": false}}`로 끌 수 있고, `context.max_chars`(기본 6000)가 요약과 최근 turn의 크기를 제한합니다. `context.enabled: false`이면 현재 프롬프트만 전송됩니다. 백그라운드 요약은 독립 실행 `claude` CLI가 로그인되어 있어야 합니다(`claude auth login`). Claude 데스크톱 앱 세션의 로그인은 CLI에 공유되지 않으며, 로그인되지 않으면 요약을 건너뛰고 오류 이벤트만 기록합니다. Codex 요약에는 `codex` CLI 로그인(`codex login`)이 필요합니다.

Codex 제한 사항: Codex 0.160.1에서는 해당 도구를 끈 `codex exec`가 직접 지시, 프롬프트 주입, `functions.exec` / `spawn_agent` 우회 시도 모두에서 canary 파일을 읽지 못했고, 플래그 없이 실행하면 읽었습니다. 이는 그 버전에 대한 행동상의 증거일 뿐 보장은 아닙니다. 다른 Codex 버전에서는 Codex 요약을 건너뛰고(오류 이벤트 기록) Codex 분류기에는 도구 비활성화 플래그와 세션 컨텍스트를 모두 넣지 않습니다. `--ignore-user-config`를 써도 전역 `~/.codex/AGENTS.md`는 계속 로드됩니다(확인: 간단한 프롬프트에도 입력 토큰 약 26k, `-c project_doc_max_bytes=0`으로도 해결되지 않음). 따라서 사용자 수준 Codex 지침은 모든 Codex 분류기·요약 호출에 토큰을 더합니다.

Jev는 기본적으로 `jev-latest` 모델을 사용합니다. API 키는 저장소 설정이 아닌 `~/.config/model-effort-router/config.json`에 저장합니다.

```json
{
  "jev": {"api_key": "your-typesafe-api-key"}
}
```

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

### 분류기 성능

합성 코퍼스 v3 150건에서 측정한 role/effort 라벨 일치율입니다.

| Backend | Role | Effort | Role + effort |
|---|---:|---:|---:|
| Jev (`jev-latest`) | 141/150 (94.0%) | 119/150 (79.3%) | 111/150 (74.0%) |
| Nimble | 124/150 (82.7%) | 101/150 (67.3%) | 85/150 (56.7%) |
| OpenAI Decisions API (`gpt-6-luna`) | 136/150 (90.7%) | 119/150 (79.3%) | 107/150 (71.3%) |

Decisions API는 API 엔드포인트이고 `gpt-6-luna`는 해당 API에서 사용하는 모델입니다. 이 코퍼스에서는 Jev가 가장 높은 일치율을 기록했습니다. 세 결과는 같은 기존 평가 케이스를 사용했으므로 독립적인 실제 사용자 정확도가 아니라 판정 라벨과의 일치율로 해석해야 합니다. Nimble은 로컬 추론에 사용할 수 있으며, 요청이 기기 밖으로 나가지 않게 하려면 fallback을 `none`으로 설정하십시오. 자세한 내용은 [평가 인덱스](docs/evaluation/README.md)와 [Decisions API 측정 기록](docs/evaluation/openai-decisions-20261007.md)을 참고하십시오.

## 사용법

```sh
python3 <plugin>/bin/mer route --host codex --json 'Review the authentication changes'
python3 <plugin>/bin/mer route --host codex --role implementation --effort high --json 'Implement the approved design'
python3 <plugin>/bin/mer run --host codex --role test --effort medium 'Run and fix the focused tests'
```

`mer route`는 분류/매핑만 수행합니다. 기본적으로 `mer run`은 worker 요청을 정확히 하나 실행합니다. 추론 역할은 읽기 전용으로 실행됩니다. Antigravity는 Subagent 격리가 검증되지 않아, OpenCode는 plugin worker 실행 계약이 없어 worker 실행을 지원하지 않습니다. OpenCode 플러그인은 `mer` 조언 도구를 제공합니다. `mer chat`은 제거되었으므로, route 결과를 사용해 Main이 선택된 Subagent를 호출하도록 요청하십시오. 명시적인 `--role`과 `--effort`는 자동 hook 적합성 판단을 우회하며, 반드시 함께 제공해야 합니다.

실행 후 MER는 worker 전후의 저장소 변경 경로를 비교합니다. 변경이 감지되면 텍스트 출력에는 `door`(`one-way`는 데이터 마이그레이션, 데이터 손실 또는 결제 위험인 경우이고, 그 외에는 `two-way`)와 예상 `blast_radius`(`local` 또는 `broad`), 변경 파일 수 및 최상위 디렉터리 수가 표시됩니다. JSON에는 결과 `risk_flags`와 함께 동일한 값이 `change` 아래에 포함됩니다. 영향 범위는 경로를 바탕으로 추정하므로 실제 변경 내용을 검토해 영향을 판단하십시오.

### Low-first worker 실행

```sh
python3 <plugin>/bin/mer run --host codex --role fix --effort low --low-first \
  --verify 'python3 -m unittest discover -s tests' --json 'Fix the approved bug'
```

실행 역할에서 `--low-first`는 고정된 검증 명령이 양의 0이 아닌 코드로 종료된 경우에만 low에서 시작해 medium, high 순서로 승격합니다. high가 실패하면 xhigh를 호출하기 전에 `status: approval_required`로 중지합니다. 사용자가 해당 실행에 대해 xhigh를 명시적으로 승인한 경우에만 `--approve-xhigh`를 전달하십시오. Agent는 이를 설정하기 전에 승인을 받아야 합니다. 설정된 모델은 네 가지 effort를 모두 지원해야 합니다. 각 시도는 같은 workspace에서 새 세션으로 시작하며, 변경 사항을 유지하고 원래 컨텍스트와 이전 실패를 함께 받습니다. Worker 오류, 취소, 검증 시작 실패, 신호 종료 및 timeout은 루프를 중지합니다. `--timeout`은 각 worker 시도를 제한하고, `--verify-timeout`은 각 검사를 제한합니다(기본값 300초).

승인 중지 결과에는 원래 요청과 마지막 실패가 담긴 `continuation_context`가 반환됩니다. 승인 후에는 같은 workspace에서 해당 context를 요청으로 전달하고 `--low-first --role <same-role> --effort xhigh --approve-xhigh --verify <same-command>`를 사용해 xhigh continuation만 실행하십시오. 이 사용량은 별도 실행으로 집계되므로, 전체 작업을 측정할 때 두 기록을 합치십시오. 명시적인 xhigh effort가 없으면 새 invocation은 low에서 시작합니다. 일회성 xhigh 실행에도 `--approve-xhigh`가 필요합니다.

`--verify`는 shell expansion 없이 parent process의 권한과 환경을 사용해 실행되는 명시적인 argv 명령입니다. 작업 시작 전에 의미 있는 완료 검사를 고정하십시오. argv를 수정해도 worker가 편집할 수 있는 테스트를 변조 방지 상태로 만들 수는 없습니다. 검사 출력의 마지막 2,000자는 다음 worker에 전송되고 JSON에도 반환되므로, 그 출력에 secret을 포함하지 마십시오. 영속 route log에는 시도 메타데이터, token 수, 검사 상태/소요 시간만 저장됩니다.

JSON과 route log에는 `first_pass`, `escalation_count`, 그리고 각 시도의 effort, worker 사용량 및 검증 소요 시간이 기록됩니다. `usage`는 보고된 worker token을 합산하고, `usage_missing`은 사용량이 없거나 불완전한 시도의 수를 셉니다. 분류기 사용량은 별도로 기록됩니다. 결정론적 검사는 실행 시간을 늘리지만 router model call은 추가하지 않습니다. 검사 내부의 외부 model call은 측정되지 않으므로 token 수치는 전체 검증 비용이 아닙니다.

탐색적 비교를 위해 `--retry-low`는 medium 전에 동일한 실패 피드백을 사용해 low 재시도를 한 번 추가합니다. 별도로 동일하게 초기화한 workspace에서 일반 low-first와 비교하고, 전체 chain과 사용량을 보고하십시오. 이미 수정된 workspace에서 두 arm을 모두 실행하지 마십시오.

Hook은 Context Packet 필드와 작성 지침을 제공할 뿐, Main의 대화에서 완성된 packet을 가져오지 않습니다. Main이 현재 요청과 관련 대화의 사실을 추려 Context Packet(`task`, `context`, `decisions`, `constraints`, `relevant_files`, `expected_result`)을 채우고 네이티브 Subagent 호출에 직접 포함해야 합니다. 검토에는 `goal`, `decisions`, `constraints`, 실제 diff, 검증 상태/결과만 전달하고 실행하지 않은 검사는 `실행 안 함`으로 표시하십시오. 기본적으로 비공개 추론 과정이나 전체 대화를 전달하지 마십시오. Hook은 Main의 대화를 읽거나 네이티브 Subagent를 직접 생성하지 않습니다. `mer run`은 별도 단일 worker 경로라 Main의 대화를 읽을 수 없으므로 필요한 컨텍스트를 명시적인 task 입력에 포함해야 합니다.

## 설정

설정은 저장소 루트의 `.model-effort-router.json` 또는 `~/.config/model-effort-router/config.json`에 JSON으로 작성합니다. 저장소 값이 사용자 값을 덮어씁니다. 기존 사용자 파일은 다시 작성하지 않습니다. 예시:

```json
{
  "router": {"mode": "auto"},
  "difficulty": {"backend": "jev", "fallback": "subscription", "timeout_s": 10},
  "models": {
    "codex": {
      "execution": {"primary": "gpt-6-luna", "alternatives": ["gpt-6-astra"], "fallback": "gpt-6.1-sol", "efforts": ["low", "medium", "high", "xhigh"]},
      "reasoning": {"primary": "gpt-6.1-sol", "alternatives": ["gpt-6-astra"], "fallback": "gpt-6-luna", "efforts": ["low", "medium", "high", "xhigh"]}
    },
    "claude": {
      "execution": {"primary": "claude-sonnet-5-5", "alternatives": ["claude-fable-5-1"], "fallback": "claude-opus-5-5", "efforts": ["low", "medium", "high", "xhigh"]},
      "reasoning": {"primary": "claude-opus-5-5", "alternatives": ["claude-fable-5-1"], "fallback": "claude-sonnet-5-5", "efforts": ["low", "medium", "high", "xhigh"]}
    },
    "antigravity": {
      "execution": {"primary": "gemini-3.8-flash", "alternatives": ["claude-opus-5-5"], "fallback": null, "efforts": ["medium", "high"]},
      "reasoning": {"primary": "claude-opus-5-5", "fallback": null, "efforts": ["medium", "high"]}
    },
    "opencode": {
      "execution": {"primary": "opencode/mimo-v2.6-flash-free", "fallback": null, "efforts": ["low", "medium", "high", "xhigh"]},
      "reasoning": {"primary": "opencode/nemotron-3-ultra-free", "alternatives": ["opencode-go/glm-5.3", "opencode-go/kimi-k3", "opencode-go/grok-4.7"], "fallback": null, "efforts": ["low", "medium", "high", "xhigh"]}
    }
  }
}
```

Legacy L1-L5, tier/profile, session, escalation 및 `nimble_jev` 설정은 마이그레이션 안내와 함께 거부됩니다. tier override는 `/router role=<role> effort=<effort>`로 바꾸고, 이전 Main-session 라우팅 workflow는 `mer route`와 Main이 선택한 Subagent 조합으로 바꾸십시오. `nimble_jev`는 제거되었으므로 `nimble`과 `jev` 같은 별도의 classifier fallback을 설정하십시오.

Jev 인증 정보는 전역 사용자 설정에만 둘 수 있습니다. 자세한 방법은 [분류기 backend 설정](#분류기-backend-설정)을 참고하십시오. 저장소 설정에는 이 인증 정보를 둘 수 없습니다.

## Runtime 개발

`model_effort_router/`가 공유 runtime source입니다. Plugin에는 host integration만 포함됩니다. 개발 시 `MER_CORE_PATH="$PWD"`를 사용하십시오. 다음 명령으로 설치하고 검증합니다:

```sh
python3 scripts/install_core.py
python3 scripts/install_core.py --check
MER_CORE_PATH="$PWD" python3 -m unittest discover -s tests
```

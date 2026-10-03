# Model-Effort Router Greenfield 기획서

> 개정: 2026-10-01 (3차) — 기준선 파일럿 결과(Router가 기준선 대비 사용량 약 3.1배)를 반영해 실행 구조를 "단계별 subagent 오케스트레이션"에서 "요청 단위 라우팅 + cascade 승격"으로 전환. 독립 Review는 고위험 작업에만 적용. Phase 7(전환) 추가.
>
> 개정: 2026-10-01 (2차) — Phase 0 spike, Phase 1~4 구현, Codex live 테스트 결과 반영. §3 실행 구조를 "지침 주입 + subagent 생성 검사"로 구체화, 호스트 제약(`mer_<stage>` 이름, `fork_turns=none`, manifest 위치, hook 신뢰) 추가, 설정 형식 JSON 확정, 구현 상태와 미결 사항 갱신.
>
> 개정: 2026-10-01 (1차) — 1차 검토 반영. 호스트 실행 모델을 "hook 개입"에서 "Router 주도 단계 실행"으로 변경, Stage Policy 단일값 확정, Effort Map·라우팅 대상 판정·Test Gate 탐색·평가 기준선 추가, Codex 우선 MVP로 범위 축소, 장 번호 정리.

## 1. 목적

Model-Effort Router는 개발 작업의 난이도를 판단하고, 그 작업을 처리할 **모델과 reasoning effort를 요청 단위로** 결정한다. 실패할 때만 상위 설정으로 올리고(cascade), 고위험 작업에만 독립 Review를 붙인다.

핵심 목표:

- 제품은 **Codex Plugin / Claude Code Plugin 형태로 배포·실행**한다. **MVP는 Codex Plugin을 먼저 완성**하고, Claude Code Plugin은 그 다음 단계로 진행한다.
- 쉬운 작업에는 저비용 모델을 사용한다.
- 설계가 필요한 작업에는 상위 모델을 배정한다.
- 한 작업은 **한 세션이 처음부터 끝까지** 처리한다. 단계마다 agent를 나누지 않는다.
- 쉬운 설정으로 시작하고, Test Gate 실패 등 근거가 있을 때만 상위 설정으로 올린다.
- 고위험 작업(L4·L5, auth·security 신호)만 구현과 리뷰를 별도 실행으로 분리하고, 리뷰에 상위 모델을 쓴다.
- Codex, Claude Code 등 각 호스트의 구독형 실행 환경을 그대로 사용한다.
- 난이도 판단기는 특정 제품에 종속하지 않고 교체 가능하게 만든다.
- 고정 모델로 실행하는 것보다 **전체 사용량이 실제로 줄어드는지** 측정으로 입증한다.

핵심 원칙:

> **Difficulty Backend가 난이도를 판단하고, Router가 요청 하나에 맞는 모델·effort로 호스트 세션을 시작하며, 실패할 때만 같은 세션을 상위 설정으로 올린다. 고위험 작업만 독립 Review를 붙인다.**

---

## 2. 제품 형태: 실행기(CLI) + Host Plugin

Model-Effort Router는 독립 LLM 서비스가 아니다. 두 가지 진입점을 제공하고, 둘 다 같은 Router Core를 쓴다.

```text
mer CLI (주 진입점)        요청을 받아 판정 → 지정 모델·effort로 호스트 세션 실행 → Test Gate → 필요 시 승격·독립 Review
Host Plugin (보조 진입점)   평소처럼 호스트 TUI를 쓸 때, 판정 결과와 권장 모델을 안내(조언). 강제하지 않음
```

대상 호스트: Codex(MVP), Claude Code(MVP 이후).

```text
mer CLI ─┐
         ├─ Router Core (Difficulty Backend, Policy, Profile)
Plugin ──┘
         ↓
Host Adapter (tier/effort → 호스트 모델·effort, 세션 실행·재개 방식)
         ↓
Host Runtime / Subscription
```

### 2.1 실행기와 플러그인의 역할

- **mer CLI**: 라우팅 대상 판정, 난이도 판정, 세션 프로필 결정, 호스트 세션 실행, Test Gate, 승격, 고위험 작업의 독립 Review, 로그
- **Host Plugin**: 요청 시점 hook으로 판정과 권장 설정 안내, `mer-gate` 제공, skill 문서

### 2.2 Router Core의 역할

```text
Router Core
├─ Difficulty Backend Contract
├─ DifficultyDecision
├─ L1 ~ L5 정의
├─ Policy (세션 프로필, 승격 사다리, 위험 신호 최소 조건)
└─ Abstract Profile (model tier + effort)
```

Codex와 Claude Code는 같은 Core를 사용하고, 실제 모델·effort 매핑과 세션 실행 방식만 다르다.

### 2.3 독립 서비스는 기본 구조가 아님

다음 구조는 초기 버전에서 사용하지 않는다.

```text
Codex/Claude → 외부 Router Server → 별도 LLM API
```

이유:

- 호스트 구독 사용량을 그대로 활용하고 별도 API 과금을 피한다.
- 설치와 실행 흐름이 단순하다.
- 호스트의 모델 선택 기능, 권한, 작업 컨텍스트를 직접 사용한다.

필요하면 추후 Router Core만 라이브러리 또는 별도 프로세스로 분리할 수 있지만 MVP 범위가 아니다.

---

## 3. 실행 모델: 요청 단위 라우팅 + cascade 승격

### 3.0 전환 배경

2차 개정까지의 구조는 한 작업을 Plan / Implement / Review subagent로 나눠 단계마다 다른 모델을 쓰는 방식이었다. 기준선 파일럿(§22.3)에서 이 구조는 기준선 대비 **전체 사용량 약 3.1배, 시간 약 2.5배**였다.

원인:

- subagent마다 시스템 프롬프트·도구 설명 등 고정 비용(턴당 약 30k 입력)이 붙는다.
- `fork_turns="none"`으로 격리한 subagent가 저장소를 각자 다시 탐색한다.
- 단계를 조율하는 메인 세션이 대기·전달 턴마다 비용을 쓴다(사례당 361k~468k).
- subagent는 원래 컨텍스트 격리·병렬 처리 수단이지 비용 절감 수단이 아니다.

따라서 업계의 일반적인 방식(요청 단위 라우팅, cascade)으로 전환한다.

### 3.1 역할 분리

```text
mer CLI                : 판정 → 세션 프로필 결정 → 호스트 세션 실행 → mer-gate → 승격 / 독립 Review → 로그
Router Core            : 라우팅 대상 판정, 난이도 판정, 세션 프로필·승격 사다리·Review 필요 여부 결정
호스트 세션            : 한 세션이 계획과 구현을 모두 수행 (L4 이상·위험 신호면 프롬프트로 "계획 먼저" 지시)
독립 Review 세션       : L4·L5와 auth·security 신호만. 새 세션, 상위 모델, 요청·diff·Test Gate 결과만 입력
Host Plugin hook       : (보조) TUI 사용 시 판정 결과와 권장 `/model` 설정을 안내. 강제 없음
```

### 3.2 호스트 기능 전제 (Codex 0.159.2)

| 항목 | 상태 | 근거 |
|---|---|---|
| 세션 시작 시 모델·effort 지정 (`codex exec -m ... -c model_reasoning_effort=...`) | 동작 | 파일럿 |
| 같은 세션을 이어서 다른 모델로 실행 (`codex exec resume <id> -m ...`) | 동작. 대화 유지, 모델 변경 턴은 캐시 대부분 끊김 | [Phase 7 spike](../spikes/phase7-session-escalation.md) |
| app-server 턴 단위 모델·effort 변경 (`TurnStartParams.model`, `effort`) | 스키마에 있음, `exec resume`이 동작해 미확인 | `generate-json-schema` |
| 사용자의 TUI `/model` 변경 | 동작 | Codex 기본 기능 |
| hook이 메인 세션 모델을 변경 | 불가로 봄 (컨텍스트 주입·허용/차단만) | spike |
| 플러그인 `UserPromptSubmit` hook 실행, 컨텍스트 주입 | 동작 | live 테스트 |
| hook timeout 초과 | fail-open 관찰 (증거 미보존) | spike |

호스트 제약 (live 테스트·spike에서 확인):

- **hook 신뢰(trust)**: 신뢰되지 않은 hook은 오류 없이 건너뛴다. 사용자가 `/hooks`에서 직접 신뢰해야 한다. 신뢰는 hook별 `trusted_hash` 단위다.
- **플러그인 manifest**: Codex는 `.codex-plugin/plugin.json`을 읽는다. 루트에 Agent Plugins `$schema`를 가진 `plugin.json`이 있으면 `hooks`·`skills`가 무시된다. hook 경로 변수는 `${CLAUDE_PLUGIN_ROOT}`.
- **subagent 이름**(subagent를 쓰는 경우): 소문자·숫자·밑줄만. `fork_turns` 기본값 `all`은 부모 대화를 복제한다.

### 3.3 라우팅 대상 판정

모든 사용자 입력을 분류기에 보내지 않는다. 먼저 저비용 규칙으로 대상 여부를 판정한다.

| 입력 유형 | 처리 |
|---|---|
| 대화, 단순 설명, 상태 질문, 코드 읽기만 필요한 질문 | 라우팅하지 않음. 호스트 기본 동작 |
| 코드 변경이 필요한 개발 작업 | 전체 라우팅 (난이도 판정 → 필요한 단계 실행) |
| 리뷰만 요청 | Review 단계만 실행. 난이도 판정은 Review 프로필 결정용으로만 사용 |
| 계획만 요청 | Plan 단계만 실행 |

판정 규칙은 Router Core에 두고, 판정이 모호하면 라우팅하지 않는 쪽을 기본으로 한다(불필요한 분류 비용 방지).

**Backend가 대상을 정하는 경우 (Jev, `provides_target`)**: 규칙(`classify_target`)은 코퍼스 150건 중 111건만 맞혔다(요청 텍스트만 줬을 때). 개발 요청인데 맥락 단어 목록에 없는 말(Dockerfile, ci.yml, ViewModel, 화면 등)이 있으면 `no_route`로 보고 hook이 침묵한다. 그래서 주 Backend가 `provides_target`이면 **규칙보다 먼저 Backend를 호출하고** `DifficultyDecision.target`(route / plan_only / review_only / no_route)을 쓴다. 결과가 `no_route`면(명시 `mer` 호출과 `session=` override가 아닐 때) 라우팅하지 않는다. 호출 결과와 분류기 사용량은 로그에 남는다(`target_source: backend`). 주 Backend는 **혼자 먼저** 호출한다. 실패하면(키 없음, 네트워크, 응답 형식) 예전 순서로 돌아가 규칙이 먼저 판정하고, `no_route`가 아닐 때만 fallback Backend(Subscription)를 호출한다. 그래서 Jev가 죽어도 잡담마다 fallback 비용(약 27k 토큰)이 들지 않는다. 실패한 주 Backend는 `fallback_cause`로 로그에 남는다(`target_source: rules`). 명시 `mer` 호출이나 `session=` override가 Backend의 `no_route`를 route로 바꾸면 `target_source: override`. target을 제공하지 않는 Backend는 지금처럼 규칙이 먼저이고 `no_route`면 분류기를 호출하지 않는다. 비용: hook에서 **모든 프롬프트마다 Jev 1회**(약 600 입력 토큰, 약 0.3초). `off`·`manual` 모드는 어떤 Backend도 호출하지 않는다.

### 3.4 실행 흐름

```text
mer "<요청>" [--cwd DIR]
 ├─ Router Core: 라우팅 대상 판정 → 난이도 판정 → 세션 프로필, 승격 사다리, Review 필요 여부
 ├─ 구현 세션 실행: codex exec -m <모델> -c model_reasoning_effort=<effort> "<요청 + 지침>"
 │     지침: L4 이상·위험 신호면 계획을 먼저 쓰고 구현, 끝나면 변경 요약
 ├─ mer-gate (Test Gate)
 ├─ 실패 → 같은 세션을 다음 승격 프로필로 재개하고 실패 내용 전달 → mer-gate  (최대 2회)
 ├─ 고위험 작업이면 독립 Review 세션 1회 (새 세션, Review 프로필, 요청·diff·gate 결과만)
 │     changes_requested → 같은 구현 세션에서 지적 반영 1턴 → Test Gate (재Review 없음)
 └─ 라우팅 로그 기록
```

- 한 작업의 계획과 구현은 같은 세션에서 이어지므로 저장소를 다시 탐색하지 않는다.
- 승격은 `codex exec resume <id> -m <모델> -c model_reasoning_effort=<effort>`로 같은 세션을 이어서 실행한다(Phase 7 spike로 확인). 모델이 바뀌는 턴은 캐시가 대부분 끊기므로, 승격 1회 비용은 그 시점까지 쌓인 대화 길이만큼의 미캐시 입력이다.
- resume 실행의 `turn.completed.usage`는 세션 누적값이다. 실행별 사용량은 차이 또는 rollout `last_token_usage`로 구한다.
- 대화형 사용(`mer --interactive`)은 판정한 설정으로 호스트 TUI를 시작만 한다. 승격·Review 자동화는 하지 않는다.

### 3.5 재라우팅

작업 범위가 실행 중 크게 바뀐 경우에만 재라우팅한다.

- 사용자가 요구사항을 추가함
- Plan 결과가 최초 분류와 다른 수준의 복잡도를 드러냄
- 예상보다 변경 범위가 크게 확대됨
- 보안·인증·결제·데이터 손실 등 새로운 위험 신호가 발견됨

```text
scope_changed → 새 DifficultyDecision → Stage Policy 재계산 → 남은 단계에만 적용
```

테스트 실패나 단순 수정 때문에 재판정하지 않는다. 재라우팅은 작업당 1회로 제한한다.

전환 후에는 재라우팅 대신 cascade 승격(§11.4)이 실행 중 조정을 맡는다. 요구사항이 추가되면 새 요청으로 다시 판정한다.

**2차 개정 구현 상태**: 명시적 재라우팅은 구현하지 않았다. 새 요청이 라우팅되면 새 RoutePlan이 이전 계획을 대체한다. 이전 계획은 모든 단계 완료, 2시간 경과, 연속 3회 비라우팅 요청 중 하나가 되면 폐기된다(짧은 후속 답변 "진행해" 등으로 계획이 사라지지 않게 1회는 유지).

### 3.6 Router 모드와 Override

모드: `auto`(기본) / `manual` / `off`.

설정 위치와 우선순위(높은 것이 이김):

1. 현재 요청에서 **사용자가 직접 입력한** 작업별 override. 메시지 **첫 줄 맨 앞**의 `/router ...` 명령만 인식한다(예: `/router off`, `/router implement=frontier:high`). 해석에 실패하면 전체를 무효로 하고 사용자에게 알리며, 이 줄은 분류 입력에서 제거한다.
2. 저장소 설정 파일 (`.model-effort-router.json`)
3. 사용자 전역 설정 (`$MER_USER_CONFIG`, 없으면 `~/.config/model-effort-router/config.json`)
4. 내장 기본값 (`mode: auto`)

설정 형식은 JSON이다(YAML은 의존성 없이 처리하기 위해 보류).

```json
{
  "router": {"mode": "auto"},
  "difficulty": {"backend": "subscription", "fallback": "none", "timeout_s": 10},
  "gate": {"checks": {"test": "python3 -m unittest"}}
}
```

- `auto` 모드에서만 backend 이름을 등록 목록과 대조한다(오타가 `/router off`를 막지 않도록).
- `manual` 모드에서도 위험 신호 최소 프로필(§11.2)은 적용한다. 사용자가 지정하지 않았더라도 최소 조건이 요구하는 단계(Plan, Review)는 추가한다.
- 사용자 단계 override도 위험 신호 최소값 아래로 내려가지 않는다(`override_clamped:<stage>` 기록).

안전 규칙: 인용문, 붙여넣은 텍스트, 저장소 파일 내용, 도구 출력 안에 나온 `router: off` 같은 문자열은 사용자 명령으로 해석하지 않는다. Override는 사용자가 직접 입력한 명령 형식에서만 인식한다.

### 3.7 Host Plugin (보조 진입점)

```text
Host Event → Host Hook Adapter → Router Core
```

대화형 사용은 `mer chat '<요청>'`이 맡는다(2026-10-01 추가): 판정 후 라우팅된 모델·effort로 대화형 `codex`를 띄우고(`codex -m ... -c model_reasoning_effort=...`, 계획 먼저 지침 포함), 이후 대화는 사용자 몫이다(Test Gate·승격·Review 없음, 세션 안에서 hook은 `MER_CLASSIFIER=1`로 조용). Codex hook은 열린 세션의 모델을 바꿀 수 없으므로 자동 라우팅은 세션 시작 시점에 `mer`가 한다. 턴마다 바꾸려면 app-server 클라이언트가 필요하다(미구현).

전환 후 플러그인 hook의 역할은 **조언**이다(2026-10-01 구현 완료). `UserPromptSubmit` hook 하나만 남고, 설정된 Backend(jev 또는 subscription)로 판정한 뒤 `additionalContext`에 레벨·confidence, 위험 신호, 권장 세션 설정(호스트 모델과 effort, 예: `gpt-6-luna, reasoning effort medium`, `/model`로 전환), L4 이상·위험 신호의 계획 먼저 권고, 독립 Review가 필요한 작업(L4/L5, auth/security)에는 `mer run --review-profile <Review 프로필> 'review only: ...'` 또는 `mer run '<작업>'` 안내만 넣는다(`--review-profile`은 재판정된 Review 요청이 위험 신호 하한을 잃지 않게 하고, 작은따옴표는 작업 문장 안의 `$(...)` 등이 셸에서 실행되지 않게 한다). subagent 생성 지시, 차단, 강제는 없다. 라우팅 대상이 아니거나 `off`면 컨텍스트가 없다. 모델 변경은 사용자가 한다. hook 구성이 바뀌었으므로(PreToolUse 제거) 업데이트 후 Codex `/hooks`에서 다시 신뢰해야 한다.

hook 공통 규칙(유지):

- **fail-open**: hook 내부 오류는 종료 코드 0, 출력 없음. 로그에 오류 종류만 기록한다.
- **재귀 방지**: 분류용 중첩 `codex exec`에는 `MER_CLASSIFIER=1`. hook은 이 값이 있으면 아무것도 하지 않는다(live 확인).
- **timeout**: hook timeout 30초, Backend `timeout_s` 최대 12초(초과 시 12로 낮추고 `timeout_clamped` 기록).

### 3.8 폐기한 설계: 단계별 subagent 오케스트레이션

2차 개정 구조(hook이 단계 지침을 주입하고, 메인 에이전트가 `mer_<stage>` subagent를 생성하고, `PreToolUse` hook이 모델·effort·이름·수정 한도를 강제)는 Phase 3에서 구현해 live로 동작을 확인했다. 그러나 파일럿에서 비용이 기준선의 약 3.1배여서 기본 구조에서 제외한다.

- **삭제 완료 (2026-10-01, 파일럿 v3 `auto_allowed` 이후)**: `host/instructions.py`(단계 지침), `host/state.py`(세션 상태·잠금·`check_spawn` 강제 규칙, `state_dir`/`log_path`만 `logging/route_log.py`로 이동), `hooks/pre_tool_use.py`와 hooks.json의 PreToolUse 항목, `policy/stages.py`(단계별 Stage Policy, 신뢰도 승격 `PromotionConfig`; 위험 신호 최소값은 `policy/session.py`로 이동), `RoutePlan.policy`, 단계 override(`/router implement=...` 등, 이제 거부됨), `mer-gate`의 `--session/--mark/--review`, SKILL.md 생성기.
- 재사용: Router Core, `mer-gate`, 라우팅 로그, 평가 도구, 분류기, 설정·override.

---

## 4. 전체 구조

```text
사용자 요청 (mer CLI, 또는 TUI + 조언 hook)
   ↓
라우팅 대상 판정
   ↓
Difficulty Backend (규칙 우선 → 필요 시 분류 모델)
   ↓
DifficultyDecision (L1 ~ L5 + risk_flags)
   ↓
Policy: 세션 프로필 + 승격 사다리 + 독립 Review 여부
   ↓
Host Adapter (호스트 모델·effort 매핑, 세션 실행·재개)
   ↓
구현 세션 (계획 + 구현) → Test Gate → [실패 시 승격] → [고위험이면 독립 Review]
   ↓
완료 + 라우팅 로그
```

Backend를 교체해도 Policy, Host Adapter, 세션 실행, Test Gate, Review는 변경되지 않는다.

---

## 5. 책임 분리

### 5.1 Difficulty Backend

작업을 입력받아 난이도를 판단하고, 결과를 공통 `DifficultyDecision`으로 정규화한다.

### 5.2 Stage Policy

`DifficultyDecision`을 받아 각 단계의 실행 프로필(model tier + effort) **하나씩**을 결정한다. Backend 내부 구현을 알지 않는다.

### 5.3 Host Adapter

추상 프로필을 호스트의 실제 모델과 effort로 변환하고 subagent를 실행한다. 모델 매핑과 effort 매핑을 모두 담당한다(§12).

### 5.4 Host Runtime

실제 LLM 실행은 Codex 또는 Claude Code가 담당한다. Router가 OpenAI API나 Anthropic API를 직접 호출하는 구조를 기본값으로 두지 않는다.

---

## 6. Difficulty Backend 인터페이스

```python
class DifficultyBackend(Protocol):
    name: str
    def classify(self, task: DifficultyInput, timeout_s: float) -> DifficultyDecision:
        ...
```

`DifficultyInput`은 작업 설명과 필요한 최소 저장소 컨텍스트(변경 예상 경로, 저장소 규모 요약 등)로 구성한다. 입력 크기 상한을 둔다.

---

## 7. DifficultyDecision

```json
{
  "level": "L3",
  "backend": "subscription",
  "confidence": 0.91,
  "distribution": {"L1": 0.01, "L2": 0.07, "L3": 0.91, "L4": 0.01, "L5": 0.00},
  "reason_codes": ["multi_file_change", "moderate_design_judgment"],
  "risk_flags": ["auth"]
}
```

필수: `level`, `backend`

권장: `confidence`, `distribution`, `reason_codes`, `risk_flags`

`risk_flags` 값: `security`, `auth`, `payment`, `data_migration`, `data_loss`, `concurrency`. Backend가 제공하지 않아도 Router Core가 작업 설명과 변경 경로에 대한 규칙 기반 탐지로 채운다. 이 규칙 탐지는 Backend와 무관하게 항상 실행한다.

`confidence`의 의미는 Backend마다 다를 수 있다. 검증 전에는 Backend 간 비교나 공통 임계값에 사용하지 않는다(§11.2).

---

## 8. Backend 후보

### 8.1 Subscription LLM Backend (MVP 기본값, 구현 완료)

호스트 구독 안의 저가 모델(economy tier)에 L1~L5 분류 프롬프트를 실행한다. 추가 설치가 없어 MVP 기본값으로 쓴다.

호출 방식: `codex exec --json --ephemeral --skip-git-repo-check --ignore-user-config -s read-only -m <economy 모델> -c model_reasoning_effort=low`를 하위 프로세스로 실행한다.

- stdin은 `DEVNULL`로 준다(파이프면 EOF까지 멈춤).
- 호출마다 빈 임시 디렉터리에서 실행한다(저장소의 `.codex/` 설정·hook이 끼어들지 않도록).
- 자식 환경에 `MER_CLASSIFIER=1`을 넣어 Router hook 재귀를 막는다.
- timeout 시 프로세스 그룹 전체를 종료한다.
- JSON 이벤트 중 `item.completed`의 `agent_message`만 읽고, 설정 경고 등 `error` 항목은 건너뛴다. 결과를 해석하지 못하면 실패로 보고 fallback으로 넘어간다.
- `turn.completed`의 사용량을 기록한다(§21).

전제 검증 결과:

| 전제 | 결과 |
|---|---|
| 플러그인 컨텍스트에서 구독 인증만으로 분류 호출 | 가능 (live 테스트) |
| 분류 지연이 hook timeout 안 | 약 4~6초 (spike p50 4.07s, live 5.1~5.5s) |
| 분류 사용량이 절감 효과를 상쇄하지 않는가 | **미해소**. 호출당 입력 약 27~30k 토큰으로, 사소한 작업 1턴과 비슷하다. §22.3 기준선 비교로 판단 |

### 8.2 Jev Backend

Jev는 TypeSafe의 외부 API다. 구현은 `difficulty/jev.py`의 `JevBackend`에 격리했다(`calls_model = True`).

- **호출**: `POST https://api.typesafe.ai/v1/systemone`, `Authorization: Bearer $TYPESAFE_API_KEY`. 키는 호출 시점에 환경에서 읽고(없으면 변수명만 담은 오류), 생성자는 네트워크·키 검사를 하지 않는다. 모델은 기본 `jev-latest`, `MER_JEV_MODEL`로 고정 버전(예: `jev-1.13.0`)을 지정한다. HTTP는 `difficulty.timeout_s`(최대 12)를 호출 전체 기한으로 강제한다(DNS·느린 응답 포함). 리다이렉트는 따르지 않고 오류로 처리하며, 인증 헤더는 리다이렉트 요청에 복사되지 않는다.
- **질문 설계**: `state` = 작업 텍스트(4000자) + 경로(50개). 질문은 `score` 하나(`level`, 기준 5개 = Subscription 프롬프트와 같은 L1..L5 설명)와 위험 플래그마다 `noul` 하나(security, auth, payment, data_migration, data_loss, concurrency).
- **대상 질문 (`choice` 하나, `provides_target = True`)**: `target`: route(코드·파일 변경 요청, 리뷰 후 수정, 계획 후 구현까지) / plan_only(계획만 쓰고 승인을 기다림) / review_only(기존 코드·diff 검토만) / no_route(질문, 설명, 잡담, 코드 맥락 없는 요청). 설명은 labeling-guide §1, §3 규칙 7~9를 따른다. 답의 `choice`(대상 이름 또는 기준 문장 그대로)를 `decision.target`으로 옮기고, 알 수 없는 값이나 답 누락은 예외다(fail closed). **choice 응답 형태는 아직 live로 확인하지 않았다**: 형태가 다르면 호출이 실패하고 fallback이 적용되며 비교 보고서의 fallback 수로 드러난다. 기록된 live 파일(`live-l4-auth.json`)은 target 질문 이전 것이라 그대로 두고 테스트에서 사본에 합성 답을 더한다.
- **매핑**: level = score 확률(키 정확히 `"0"`..`"4"`)의 argmax(동률이면 높은 레벨, 안전 방향). distribution = 확률(합이 1이 아니면 재정규화), confidence = 답의 confidence, 위험 플래그 = noul >= 0.5(bool 허용). 실제 응답으로 확인하기 전까지 **문서와 다른 형태는 모두 실패로 처리한다**: 확률 키가 다르거나, 확률 없이 score만 있거나, 위험 답이 없거나 확률이 아니면 예외. `reason_codes` = `("jev", <응답 model>)`. 사용량은 `input_tokens`/`output_tokens`로 보고한다.
- **실패**: non-2xx(리다이렉트 포함), 네트워크 오류, timeout, JSON 오류, 답 누락·무효는 모두 예외로 올려 fallback 체인이 처리한다(오류 코드·rate limit 문서 없음). 답을 쓸 수 없어도 응답에 사용량이 있으면 기록한다.
- **비용·프라이버시**: 구독이 아니라 외부 API로 별도 과금된다(벤더 공시 입력 약 $0.042/M 토큰, 호출당 입력 수백 토큰). **작업 텍스트와 경로가 TypeSafe로 전송된다.** 평가에서는 `--live` 없이 호출되지 않는다.
- **live 확인 (2026-10-01, 1회)**: 파일럿 L4 인증 작업으로 `jev-latest`(응답 model `jev-1.13.0`)를 호출했다. 응답 형태는 문서와 같았다(score 확률 키 `"0"`..`"4"`, `legend`가 우리 기준 순서를 그대로 반환, noul은 float). 결과: L3(확률 L2 0.33 / L3 0.51 / L5 0.13, confidence 0.49), security 0.95·auth 0.99. 사용량 입력 541 / 출력 119 토큰(Subscription 분류기 약 27k 대비 약 2%). 응답은 `tests/fixtures/jev/live-l4-auth.json`에 저장했다.
- **미검증**: 오류 응답 본문, rate limit, 분류 품질(코퍼스 비교 필요).

### 8.3 Nimble Backend (선택 기능, MVP 제외)

Bespoke Nimble은 텍스트와 스키마를 입력받아 선택지 중 하나와 선택지별 확률을 반환하는 typed-decision 모델이다.

```text
Input : 작업 설명 + 필요한 저장소 컨텍스트
Schema: difficulty = [L1, L2, L3, L4, L5]
Output: L3 + L1~L5 확률 → DifficultyDecision
```

로컬 실행은 모델·런타임 설치가 필요해 설치 단순화 목표와 충돌한다. 따라서 선택 기능으로 두고, Routing Corpus로 성능을 검증한 뒤에만 기본값 후보로 올린다.

---

## 9. Backend 선택, Registry, Fallback

설정으로 Backend를 선택한다.

```json
{"difficulty": {"backend": "subscription", "fallback": "none", "timeout_s": 10}}
```

`backend`에는 등록된 이름(현재 `subscription`, `jev`), `fallback`에는 다른 backend 이름 또는 `none`을 쓴다. `timeout_s`는 최대 12초다(§3.7).

Registry:

```python
BACKENDS = {
    "subscription": SubscriptionBackend,
    # "jev", "nimble": Phase 6
}
```

Backend를 추가해도 Router Core를 수정하지 않는다.

Fallback 흐름:

```text
primary backend
 ↓ timeout / invalid result
fallback backend (설정 시)
 ↓ timeout / invalid result
기본 결정: level = L3, backend = "default"
```

모든 Backend가 실패하면 L3를 사용한다. 단 L3는 일반 작업 기준이며, `risk_flags`에 따른 최소 프로필(§11.2)은 기본 결정에도 그대로 적용한다.

- 실패 원인은 `<backend 이름>:<예외 종류>` 형태로 기본 결정의 `reason_codes`에 남긴다.
- 모델을 호출하는 backend는 실패했더라도 보고된 사용량을 합산해 기록한다. 호출은 했지만 사용량이 없으면 `classifier_usage: null`로 명시한다(§22.3에서 "측정 불가"로 처리).
- 설정의 backend 이름 오류는 실행 중 L3로 넘기지 않고 설정 오류로 바로 알린다.

---

## 10. 난이도 체계

난이도는 `L1 ~ L5`로 고정한다. Backend가 바뀌어도 Level 정의는 바꾸지 않는다.

- **L1 — Mechanical**: 판단이 거의 필요 없는 기계적 변경. rename, 단순 문자열 변경, 명확한 config 수정, 반복적인 소규모 수정.
- **L2 — Local Change**: 한 기능 또는 소수 파일 범위의 일반 변경. 단일 함수 수정, 제한적 버그 수정, 소규모 API 수정.
- **L3 — Multi-file / Moderate**: 여러 파일·모듈에 영향이 있고 설계 판단이 필요한 작업. 여러 컴포넌트 연동, API와 서비스 계층 동시 변경, 상태 흐름 변경.
- **L4 — Architectural**: 구조 변경이나 중요한 기술 판단이 필요한 작업. 아키텍처 변경, persistence 구조 변경, concurrency 설계, 주요 API contract 변경.
- **L5 — Critical / Deep**: 높은 수준의 추론과 검증이 필요한 작업. 복잡한 동시성 문제, 대규모 구조 재설계, 보안 핵심 로직, 데이터 손실 위험 migration, 원인 불명 복합 장애.

---

## 11. Stage Policy

Stage Policy는 단계마다 **모델 tier 하나와 effort 하나**를 반환한다. 범위값은 사용하지 않는다.

적용 순서: **레벨 기본값 → 위험 신호 최소 프로필 → (검증된 경우) 불확실성 승격 → 사용자 override**

### 11.1 레벨별 기본값 (2차 개정 단계별 표, 3차 개정에서 §11.4로 대체, 코드 삭제됨)

| Level | Plan | Implement | Review |
|---|---|---|---|
| L1 | 생략 | economy / medium | economy / medium |
| L2 | 생략 | economy / medium | frontier / high |
| L3 | frontier / high | balanced / high | frontier / high |
| L4 | frontier / high | frontier / high | frontier / high |
| L5 | frontier / xhigh | frontier / high | frontier / xhigh |

이 표는 초기값이며 §22 평가 결과로만 조정한다. Difficulty Backend와 완전히 분리한다.

### 11.2 승격 규칙

**위험 신호 최소 프로필** (항상 적용):

| risk_flags | 최소 조건 |
|---|---|
| `security`, `auth`, `payment` | Plan 수행(frontier / high 이상), Review frontier / high 이상 |
| `data_migration`, `data_loss` | Plan 수행(frontier / high 이상), Review frontier / xhigh |
| `concurrency` | Review frontier / high 이상 |

최소 조건은 기본값보다 낮출 때 쓰지 않는다. 기본값이 이미 높으면 기본값을 유지한다. 사용자 override(§3.6)와 manual 모드에도 적용한다.

`risk_flags`는 Backend 출력과 규칙 기반 탐지(작업 설명·경로의 키워드)를 합친다. 규칙 탐지는 Backend와 무관하게 항상 실행한다. Backend가 모르는 값을 내면 버린다.

**불확실성 승격** (Backend별 검증 후 활성화):

- `confidence`가 Backend별 임계값보다 낮으면 level을 한 단계 올려 정책을 적용한다.
- 임계값은 Backend마다 Routing Corpus로 보정한다. 보정 전에는 비활성 상태로 둔다.
- 공통 임계값은 사용하지 않는다.

### 11.3 출력 (2차 개정 단계별 형식, 코드 삭제됨)

```json
{
  "level": "L3",
  "stages": [
    {"stage": "plan", "tier": "frontier", "effort": "high"},
    {"stage": "implement", "tier": "balanced", "effort": "high"},
    {"stage": "test_gate"},
    {"stage": "review", "tier": "frontier", "effort": "high"}
  ],
  "applied_rules": ["level_default", "risk_min:auth"]
}
```

### 11.4 세션 프로필과 승격 사다리 (3차 개정, Phase 7)

§11.1의 단계별 표 대신, 요청 하나에 쓸 **세션 프로필**과 실패 시 **승격 사다리**를 정한다.

| Level | 시작 프로필 | 1차 승격 | 2차 승격 | 독립 Review |
|---|---|---|---|---|
| L1 | economy / medium | economy / high | balanced / high | 없음 |
| L2 | economy / medium | balanced / high | frontier / high | 없음 |
| L3 | balanced / high | frontier / high | frontier / xhigh | 없음 |
| L4 | frontier / high | frontier / xhigh | 중단 후 사용자 보고 | frontier / high |
| L5 | frontier / xhigh | 중단 후 사용자 보고 | — | frontier / xhigh |

- **승격 조건**: Test Gate `failed`만. 독립 Review `changes_requested`는 승격하지 않고, **같은 구현 세션을 현재 프로필로 1턴 이어 지적을 반영**한 뒤 Test Gate만 다시 돈다(재Review 없음, 상태 `review_fixed`, gate가 실패하면 `gate_failed`). 세션 id가 없으면 반영 없이 `changes_requested`(종료 코드 1). 파일럿 재측정에서 Review → 승격 → 재Review 루프는 비용을 키웠고, L4 인증 재측정에서는 보고만 하는 Review가 찾은 결함이 그대로 남았다. `not_run`만 있는 경우도 승격하지 않고 보고에 남긴다.
- **빈 변경**: 구현 대상인데 구현 세션 전 깨끗했던 작업 트리가 세션 뒤에도 그대로면 같은 세션을 1턴 재개해 변경을 요구한다(`nudge`, 같은 프로필·subagent 정책). 그래도 그대로면 Gate·Review 없이 `no_changes`(종료 코드 1). 세션 전부터 변경이 있던 트리는 검사하지 않는다(이미 바뀐 파일의 추가 수정은 diff로 구별할 수 없음). 측정 B'에서 도구 호출 없이 "변경했다"고 답한 세션이 `ok`로 끝난 것을 막는다.
- **위험 신호**: §11.2 최소 조건을 그대로 쓰되, "Plan 수행"은 같은 세션에서 계획을 먼저 쓰게 하는 지침으로(계획 먼저는 Plan 최소값이 있는 위험 신호(concurrency 제외)와 L4 이상에만 붙는다. L3 단독에는 붙이지 않는다: 파일럿에서 턴 수만 늘렸다), "Review 최소값"은 독립 Review 프로필의 하한으로 적용한다. L1~L3에는 **auth·security 신호가 있을 때만** 독립 Review(frontier/high 이상)를 붙인다(레벨을 낮게 판정해도 인증·보안 작업의 Review가 빠지지 않게). 그 밖의 위험 신호만으로는 붙이지 않는다(파일럿 v2: 구현 세션의 자체 리뷰와 중복돼 사용량이 두 배가 됐다).
- **사용자 override**: `/router session=frontier:high`처럼 세션 프로필을 지정할 수 있다. 위험 신호는 기본값이든 override든 세션 프로필을 올리지 않는다. 대신 계획 먼저 쓰기와 독립 Review 하한은 override로 없앨 수 없다.
- 이 표는 초기값이며 파일럿 재측정(Phase 7)과 §22 평가로 조정한다. 현재 Codex에서는 economy와 balanced가 같은 모델(gpt-6-luna)이라, 낮은 단계의 승격은 사실상 effort 상승이다.
- **Codex subagent 정책** (per-call `-c` 덮어쓰기만 쓰고 사용자 설정은 건드리지 않는다): 사용자 전역 AGENTS.md가 세션마다 subagent를 1~5개 띄우게 하는 것이 남은 가장 큰 비용 요인이다(codex-cli 0.159.2에서 `codex debug prompt-input`으로 확인: `agents.enabled=false`는 멀티에이전트 역할 프롬프트와 `spawn_agent`를 제거하고, `agents.max_concurrent_threads_per_session=N`은 동시 수만 제한한다. N=0이나 문자열은 이 키 이름으로 거부되므로 키가 실제로 인식된다. 총 생성 개수는 강제할 수 없다).
  - 구현 세션과 승격 재개: L1~L4는 `agents.enabled=false`, L5는 `agents.enabled=true` + `max_concurrent_threads_per_session=1`이고 프롬프트에 한 문장을 더한다("독립 탐색이 결과를 실질적으로 개선할 때만 subagent를 쓰고, 코드 검색·테스트 실행·반복 확인의 병렬화에는 쓰지 않는다"). 레벨이 없는 manual 모드는 플래그 없음(Codex 기본값).
  - 독립 Review 세션과 Review 수정 턴은 항상 `agents.enabled=false`(수정 턴 지시문이 subagent를 금지하므로 L5도 같다. 기존 "subagent를 쓰지 말 것" 프롬프트도 유지). `plan_only`와 `mer chat`은 바꾸지 않는다.
  - 스위치: 설정 `{"session": {"subagent_policy": "level" | "codex"}}`. `level`(기본)은 위 정책, `codex`는 agents 플래그를 어디에도 붙이지 않는 현재 동작이다(A/B 측정용). 평가 도구는 `--subagent-policy`로 workdir 설정에만 써 넣고 실행 기록의 `subagent_policy`, `implement_subagents`로 남긴다. 호출 기록(`calls[].subagents`)에도 값이 남는다.

---

## 12. Host Model Map / Effort Map

Router는 실제 모델 이름 대신 추상 tier와 추상 effort를 사용한다.

```text
tier   : economy | balanced | frontier
effort : medium | high | xhigh
```

Host Adapter가 두 가지를 모두 매핑한다.

Codex adapter 현재 기본값(데이터로 관리, 확인 필요 항목 포함):

| tier | 모델 | 지원 effort |
|---|---|---|
| economy | gpt-6-luna | low, medium, high, xhigh, max |
| balanced | gpt-6-luna (economy와 같음, 확인 필요) | 위와 같음 |
| frontier | gpt-6.1-sol (2026-10-01 변경, 이전 gpt-6-sol; Codex 목록 최상위·사용자 기본 모델) | low, medium, high, xhigh, max, ultra |

추상 effort `medium / high / xhigh`는 Codex effort 이름과 같다. 현재 두 모델 모두 세 값을 지원하므로 대체 규칙이 발동하지 않는다. Codex는 미지원 effort 지정 시 subagent 생성을 오류로 거부하므로, Adapter 설정 생성 시점에 검증한다.

Claude Code adapter(Phase 5): economy = Haiku 계열, balanced = Sonnet 계열, frontier = Opus 계열.

**모델별 지원 effort 처리**

- Adapter는 모델별 지원 effort 목록을 가진다.
- 요청 effort를 선택한 모델이 지원하지 않으면 지원되는 값 중 **가장 가까운 상위값**, 상위값이 없으면 **최대 지원값**을 적용한다.
- 요청값과 실제 적용값을 모두 라우팅 로그에 기록한다.

모델 버전이 바뀌어도 Difficulty Backend와 Stage Policy는 수정하지 않는다. Adapter 설정만 갱신한다.

---

## 13. Plan 단계

Plan은 다음을 정리한다: 요구사항 해석, 변경 대상, 접근 방법, 예상 변경 범위, 구현 순서, 테스트 방법, 주요 위험 요소.

3차 개정부터 Plan은 별도 실행이 아니다. L4 이상이거나 위험 신호가 있으면 구현 세션에 "계획을 먼저 쓰고 구현하라"는 지침을 넣는다. 계획과 구현이 같은 세션에서 이어지므로 저장소를 다시 탐색하지 않는다.

---

## 14. Implement 단계

Implement는 계획을 실제 코드 변경으로 바꾼다.

비용 절감 지점은 두 가지다.

- 쉬운 작업을 저가 프로필로 **시작**하는 것
- 실패한 작업만 **승격**하는 것(cascade)

단계마다 다른 모델을 쓰는 차등 배정은 agent 분리 비용 때문에 작은 작업에서 오히려 비쌌다(§3.0).

---

## 15. Deterministic Test Gate

Implement와 Review 사이에 deterministic gate를 둔다. Test는 별도 LLM 역할로 정의하지 않는다.

검사 종류: unit test, lint, type check, build, 정적 검증.

**검사 명령 탐색 순서**

1. Router 설정 파일의 명시 명령
2. 저장소 지침 문서(`AGENTS.md`, `CLAUDE.md` 등)와 CI 설정
3. manifest scripts (`package.json`, `pyproject.toml`, `Makefile` 등)

**결과 상태**: `passed` / `failed` / `not_run`

- 찾지 못한 검사는 `not_run`으로 기록하며 통과로 취급하지 않는다. 하나라도 `not_run`이면 전체 결과는 `incomplete`다.
- 결과 전체(`not_run` 포함)를 Review 컨텍스트에 포함한다.

구현: `mer-gate` CLI. 메인 에이전트가 자신의 셸 도구로 호출하므로 호스트의 샌드박스·승인이 그대로 적용된다. hook에서는 절대 실행하지 않는다(저장소가 정의한 명령을 실행하기 때문).

- 지침 문서(`AGENTS.md`, `CLAUDE.md`)는 코드 블록 안의 명령만 읽는다. 셸 연산자(`&&`, `|`, `;` 등)나 glob 문자가 든 탐색 명령은 건너뛴다(`not_run`). 설정의 `gate.checks`만 셸로 실행한다.
- 검사마다 timeout을 두고, 초과 시 프로세스 그룹 전체를 종료한다.

---

## 16. Review 단계

Review는 구현 결과를 독립적으로 검증한다.

확인 항목: 사용자 요구사항 충족, 구현 누락, 논리 오류, 회귀 가능성, 엣지 케이스, 설계 위반, 보안 문제, 과도한 변경, 테스트 누락.

**독립성 원칙**: 독립 Review는 구현과 **별도 실행, 별도 컨텍스트**로 수행한다. 구현 세션의 대화 기록을 이어받지 않고, §17의 전달 항목만 입력으로 받는다.

**적용 범위 (3차 개정)**: 독립 Review는 L4·L5와 auth·security 신호가 있는 작업에 붙인다(§11.4). 다른 위험 신호는 Review의 프로필 하한만 올린다(파일럿 v2에서 L1~L3 위험 작업마다 붙인 Review는 구현 세션의 자체 리뷰와 중복됐다). 별도 실행마다 고정 비용(턴당 약 30k 입력)이 들기 때문이다. 그 외 작업은 Test Gate 결과와 구현 세션의 변경 요약으로 끝낸다.

Review effort 기준:

| 작업 | Review Effort |
|---|---|
| 단순 rename / 오탈자 | medium |
| 일반 코드 변경, 여러 모듈 변경 | high |
| 아키텍처, concurrency, 인증/보안 | high |
| migration / 데이터 손실 위험 | xhigh |
| L5 Critical | xhigh |

---

## 17. 단계 간 컨텍스트 전달

> 3차 개정: 계획과 구현은 같은 세션이므로 전달이 필요 없다. 아래 표는 독립 Review(고위험 작업)와 승격 재개 시의 입력에만 적용한다.

각 단계는 이전 단계의 대화 전체가 아니라 정해진 산출물만 받는다.

| 단계 | 입력 |
|---|---|
| Plan | 사용자 요청, 저장소 컨텍스트 |
| Implement | 사용자 요청, Plan 결과(있을 때) |
| Test Gate | 작업 트리 |
| Review | 사용자 요청, Plan 결과, 변경 diff, Test Gate 결과 |
| Fix | Review 또는 Test 실패 내용, 변경 diff |

전달 산출물의 크기 상한을 두고, 초과 시 요약이 아니라 경로·범위 참조로 넘긴다.

전달은 메인 에이전트가 한다. 단계 subagent는 `fork_turns="none"`으로 생성되어 이전 대화를 보지 못하므로, 메인 에이전트가 위 항목을 `spawn_agent`의 메시지에 담아 넘긴다. subagent 결과는 전문이 메인 에이전트에게 돌아온다(spike 확인 범위 약 2KB, 큰 diff는 미검증). 모든 agent가 같은 작업 트리를 공유하므로 diff는 파일 경로 참조로도 넘길 수 있다.

---

## 18. 실행 예시

**L1**

```text
구현 세션: economy/medium → Test Gate 통과 → Done
```

**L2 (테스트 실패 1회)**

```text
구현 세션: economy/medium → Test Gate 실패 → 같은 세션 balanced/high로 재개해 수정 → Test Gate 통과 → Done
```

**L2 + risk_flags=[auth]**

```text
구현 세션: economy/medium (계획 먼저 지침) → Test Gate 통과 → 독립 Review: frontier/high (auth 신호) → Done
```

**L5**

```text
구현 세션: frontier/xhigh (계획 먼저 지침) → Test Gate → 독립 Review: frontier/xhigh → Done
```

---

## 19. 실패 처리

초기 버전에서는 복잡한 Recovery Framework를 만들지 않는다.

```text
Test Fail   → 현재 Implement 프로필로 Fix → Test Gate
Review Fail → 현재 Implement 프로필로 Fix → Test Gate → Review
```

- 수정 시도는 작업당 최대 2회로 제한한다. 반복 실패하거나 사용자 결정이 필요하면 중단하고 보고한다.
- Backend·subagent timeout과 사용자 취소 시, 같은 단계를 중복 실행하지 않도록 단계별 실행 상태(`pending / running / done / failed / cancelled`)를 기록하고 재시도 전에 확인한다.

3차 개정에서는 Fix가 "같은 세션을 승격 프로필로 재개"가 되고(§11.4), 최대 2회 제한은 `mer` CLI가 지킨다. 아래는 2차 개정 구현(단계별 subagent)의 규칙이며 Phase 7 정리 때 함께 삭제한다.

2차 개정 구현(PreToolUse hook이 강제):

- 첫 Implement 이후의 모든 Implement 재생성은 수정 1회로 센다. 이전 단계가 완료·실패·취소·장시간 정지 중 어느 상태였든 같다(`--mark failed`로 한도를 우회하지 못하게). 세 번째 재생성은 차단한다.
- `running` 상태 단계의 재생성은 차단한다. 30분 넘게 `running`이면 멈춘 것으로 보고 재생성을 허용한다.
- 호스트가 생성을 거부한 호출도 이미 허용 판정을 받았다면 1회로 센다(알려진 한계).
- 취소 시 subagent와 하위 셸 프로세스가 함께 종료되는 것은 spike에서 관찰했다(증거 미보존). 취소 후 재요청 시 중복 실행은 미검증이다.

---

## 20. 사용자 질문 기준

다음 경우에만 사용자에게 질문한다.

- 요구사항이 둘 이상으로 해석됨
- 제품 또는 설계 방향 선택 필요
- 파괴적 변경 승인 필요
- 요구사항 충돌
- 반복 수정으로 해결되지 않음
- 사용자만 제공할 수 있는 정보 필요

단순 Test/Review 실패마다 질문하지 않는다.

---

## 21. 라우팅 로그

작업마다 다음을 로컬에 기록한다.

- 라우팅 대상 판정 결과
- `DifficultyDecision` 전체, 사용한 backend와 fallback 여부, 분류 지연
- Stage Policy 출력과 적용 규칙(`applied_rules`)
- 단계별 요청 프로필과 실제 적용 모델·effort
- Test Gate 결과
- Review 결과, Fix 횟수, 재라우팅 여부
- 단계별·전체 사용량과 소요 시간(호스트가 제공하는 범위)

구현: 세션별 JSONL 파일(`$MER_STATE_DIR` 또는 `~/.local/state/model-effort-router/<session>.log.jsonl`). 이벤트 종류는 `route`, `stage_spawn`, `gate`, `stage_mark`, `review`, `error`다.

- 프롬프트 원문은 저장하지 않고 해시와 길이만 남긴다. 오류는 예외 종류만 기록한다.
- 분류 호출 사용량은 `route` 이벤트에 들어간다.
- 단계 subagent와 메인 세션 사용량은 호스트 rollout 파일의 `token_count` 이벤트(누적값)에서 평가 도구가 읽는다. `codex exec --json`은 subagent 사용량을 보고하지 않는다. rollout의 `session_meta`에 있는 `agent_path`(`/root/mer_<stage>`)로 단계를 구분한다(live 테스트 확인).
- 재라우팅은 명시 표시가 없으며, 같은 세션의 두 번째 `route` 이벤트로만 나타난다.

로그는 예측과 실행 결과를 제공할 뿐 **정답 라벨이 아니다**. Routing Corpus 후보 수집에 사용하되, 라벨은 §22.1 절차로 붙인다.

---

## 22. 평가

### 22.1 Routing Corpus

- **라벨 기준**: §10 Level 정의와 레벨별 예시 작업 목록(앵커)을 문서로 고정한다.
- **라벨 담당**: 최소 2명이 독립 라벨링한다.
- **불일치 처리**: 1단계 차이는 논의 후 합의, 2단계 이상 차이는 기준 문서를 보완한 뒤 재라벨링한다.
- **표본 구성**: L1~L5 각 레벨과 위험 신호 작업을 모두 포함한다. 초기 목표 150건 이상.
- 라우팅 로그는 후보 수집원으로만 쓴다.

구현: 라벨 기준은 [labeling-guide.md](../evaluation/labeling-guide.md), 형식과 일치도 계산은 `evaluation/cases.py`. 초기 후보 40건(`evaluation/corpus/seed.jsonl`)은 모두 `draft`이며 정답 라벨이 아니다. **확정 라벨 0건**이 현재 상태다.

### 22.2 Backend 비교

같은 Corpus에서 Backend를 직접 비교한다. 이름이나 공개 benchmark만 보고 기본값을 바꾸지 않는다.

- Exact Level Accuracy
- ±1 Level Accuracy
- Over-routing / Under-routing
- Critical task miss (L4·L5 또는 위험 신호 작업을 L2 이하로 판정)
- latency, token usage, cost, local resource usage
- confidence 보정 결과(§11.2 임계값 산출용) — Phase 6
  - Jev (2026-10-04, 오프라인, `runs/compare-v1-jev-dist.json`의 분포 최댓값을 confidence로, corpus-v1 합의 라벨 109건): confidence 0.9 이상 66건 정확 95%, 0.7~0.9 25건 80%, 0.5~0.7 14건 57%, 0.5 미만 4건 25%로 잘 보정돼 있다. 그런데 낮은 confidence의 오답은 대부분 높게 본 쪽(0.5~0.7 구간 과대 36%, 과소 7%)이고, 과소는 전체 4건, critical miss는 0건이다.
  - 불확실성 승격 시뮬레이션(confidence < t면 한 단계 올림): t=0.5 과소 4→3·과대 13→14, t=0.7 과소 2·과대 20, t=0.9 과소 1·과대 38. 줄이는 과소보다 늘리는 과대가 훨씬 많아 Jev에는 켜지 않는다(비활성 유지). 라벨이 모델 합의라 사람 라벨(`human-review-30.tsv`)로 다시 확인한다.
  - Subscription: confidence 데이터가 시드 40건뿐이라 보정하지 않는다(비활성 유지).

구현: `evaluation/compare.py`. 모델을 호출하는 비교는 `--live`에서만 실행한다.

**시드 40건 비교 결과** (2026-10-01, `evaluation/corpus/seed-labeled.jsonl`, 라벨러 claude·opus 2명 합의, no_route 4건 제외 36건 채점, `runs/compare-seed.md`)

| Backend | 정확 | ±1 | 높게 / 낮게 | 평균 거리 | critical miss | p50 지연 | 입력 토큰 (40회) |
|---|---|---|---|---|---|---|---|
| jev | 31/36 (86%) | 35/36 (97%) | 5 / 0 | 0.17 | 1/18 | 270ms | 19k |
| subscription | 28/36 (78%) | 36/36 (100%) | 6 / 2 | 0.22 | 1/18 | 5.7s | 983k |

- Jev가 정확도·지연·비용 모두 앞선다(입력 토큰 약 1/50, 지연 약 1/20). Jev는 낮게 판정한 사례가 없고 높게 5건(seed-012 L1→L2, 016 L2→L3, 033·034 L3→L4, **036 L3→L5**, 2단계). subscription은 보안 핵심 작업 2건(027, 031 L5)을 L4로 낮게 봤다.
- 판정 규칙 기반 target 분류는 35/40: 개발 요청 4건(012, 019, 025, 030)을 no_route로 봐 hook이 조언하지 않는다(`mer`는 명시 실행이라 영향 없음). seed-040("Fix the login bug", 맥락 없음)은 route로 봤다. → 보완(2026-10-01): 변경 동사(bump, adjust, support, make, redesign, design, introduce 등, 한국어 늘려·지원·설계·도입·분리·옮겨·적용·개선)와 코드 맥락 단어(service, cache, db, scheduler, session, token, auth, login 등, 한국어 세션·저장소·캐시·인증·결제 등)를 추가해 39/40(경로 없이 문장만으로도 39/40). seed-040은 그대로 route로 둔다: hook은 저장소 안에서 실행되므로 실제 사용에서는 맥락이 있다.
- 정규식 위험 신호(모든 Backend 공통으로 추가됨): 정답 22개 중 13개 탐지, 오탐 2. Backend별 위험 신호는 비교 도구가 아직 기록하지 않는다(보완 필요).
- 한계: 라벨러가 둘 다 AI이고 40건이다. 목표 150건과 사람 라벨이 남아 있다.

**Jev 위험 신호 측정** (2026-10-01, 같은 40건, `runs/compare-seed-jev.md`)

- 레벨: 33/36 정확(92%), ±1 100%, 낮게 0건(같은 입력의 앞선 실행은 31/36: 실행마다 약간 다르다).
- 위험 신호: Jev 단독 재현율 21/22(95%), 정밀도 21/41(51%). 정규식과 합치면 22/22, 정밀도 51%. 정규식 단독은 13/22, 정밀도 87%.
- **Jev는 위험 신호를 과하게 붙인다**(오탐 20개): security 8, payment 5, concurrency 5, data_loss 2 등. 예: 이메일 입력 검증·업로드 리뷰에 security, 통화 포맷·폼 상태에 payment, 캐시·이벤트 버스에 concurrency.
- 영향: security·auth 오탐은 L1~L3에도 독립 Review를 붙이고(§11.4), 위험 신호는 계획 먼저 쓰기를 붙여 비용을 늘린다. 다음 단계로 noul 원값을 기록해 임계값(현재 0.5)을 신호별로 정한다.
- **임계값 보정** (2026-10-01, noul 원값 기록 후 재실행 `runs/compare-seed-jev2.json`): 신호별 임계값 security 0.85, auth 0.5, payment 0.95, data_migration 0.7, data_loss 0.75, concurrency 0.8(`difficulty/jev.py` `RISK_THRESHOLDS`). 같은 기록에서 정규식과 합친 결과가 재현율 22/22 유지, 정밀도 51% → 79%(오탐 21 → 6). auth·payment·data_migration 일부는 정규식이 이미 잡아 임계값을 높여도 놓치지 않는다. 보정과 평가가 같은 40건이라 과적합 위험이 있으므로 코퍼스를 늘리면 다시 확인한다.

**코퍼스 150건 비교** (2026-10-01, `evaluation/corpus/corpus-v1.jsonl`, Jev만, `runs/compare-v1-jev.md`)

| 항목 | 결과 |
|---|---|
| 라우팅 대상 | Jev 147/150 (98%), 규칙 요청 텍스트만 111/150 (74%), 규칙 경로 포함 131/150 |
| 레벨 (130건) | 정확 109 (84%), ±1 128 (98%), 높게 16 / 낮게 5 |
| 2단계 이상 틀림 | exp-056 L3→L5, exp-069 L5→L3(결제·동시성 L5를 L3로) |
| 비용 | 150회 입력 109k / 출력 25k, p50 245ms, fallback 0 |

- Jev target 오답 3건은 모두 맥락 없는 요청("Fix the login bug", "그거 좀 고쳐줘", "Make it faster.")을 route로 본 것이다. hook은 저장소 안에서 실행되므로 실사용 영향은 작다.
- critical miss 지표 정정: 위험 신호가 있는 L2 작업을 L2로 맞힌 경우도 miss로 세고 있었다(6건 모두 이 경우). 이제 "정답보다 낮게, L2 이하로 판정"만 센다.
- **위험 신호 임계값 재보정**: 시드 40건으로 정한 값은 새 110건(보정에 쓰지 않은 표본)에서 재현율 88%, 정밀도 65%로 떨어졌다(과적합). 150건 전체로 재현율 우선 재보정: security 0.6, auth 0.6, payment 0.95, data_migration 0.7, data_loss 0.6, concurrency 0.6. 정규식과 합쳐 재현율 68/70(97%), 정밀도 59%. L1~L3에서 security·auth 오탐으로 불필요한 Review가 붙는 작업은 130건 중 9건. concurrency 오탐은 L4·L5 Review 하한만 올리므로 비용 영향이 작다. 이 값도 같은 표본에서 정했으므로 다음 코퍼스 추가 때 보류 표본으로 다시 확인한다.

### 22.3 비용 기준선

분류기가 정확해도 분류 호출, 상위 모델 조정, 단계별 컨텍스트 전달, 재시도 비용이 합쳐지면 오히려 비싸질 수 있다. 따라서 다음을 비교한다.

```text
Baseline : 사용자 기본 모델 하나로 전체 작업 실행
Router   : 라우팅 적용 실행
```

측정 항목:

- 품질: 요구사항 충족, Review 지적 수, 사후 결함
- 전체 사용량: **메인 세션(오케스트레이션) + 분류 호출 + 모든 subagent** 합계
- 완료 시간
- 재작업(Fix) 횟수

메인 세션이 상위 모델로 동작하면 하위 단계를 저가 모델로 돌려도 절감 효과가 줄어든다. 메인 세션 사용량을 반드시 합산한다.

Router가 Baseline보다 품질을 유지하면서 전체 사용량을 줄이지 못하면 기본 모드를 `auto`로 두지 않는다.

구현: `evaluation/usage.py`(사용량 합산), `evaluation/baseline.py`(판정), `evaluation/live_runner.py`(`--live`에서만 실행). 판정은 `auto_allowed` / `do_not_default_to_auto` / `insufficient_data` 중 하나다. 다음 중 하나라도 있으면 `auto_allowed`를 내지 않는다.

- Router가 실제로 동작하지 않은 실행(route·stage_spawn 이벤트 없음)
- 기준선 실행에 Router 흔적이 섞인 실행
- 오류로 끝난 실행
- 사용량을 확인할 수 없는 실행(subagent rollout에 사용량 없음, 분류 사용량 `null`)

live 실행 전제: 사용자가 플러그인을 설치하고 hook을 직접 신뢰한다. 평가용 작업 디렉터리는 하나로 고정해(`.mer-eval-workdir` 표식이 있는 경우만 초기화) Codex 전역 설정에 신뢰 항목이 1개만 남게 한다.

**첫 live 관측값** (2026-10-01, L2 작업 1건, 메인 세션 gpt-6-luna/low, 기준선 비교 아님):

| 구분 | 입력 토큰 | 비고 |
|---|---:|---|
| 메인 세션(오케스트레이션) | 약 321k | |
| Implement (gpt-6-luna/medium) | 약 153k | |
| Review (gpt-6-sol/high) | 약 34k | |
| 분류 호출 | 약 27k | |
| 합계 | 약 535k | 약 77초 |

메인 세션이 구현 단계의 약 2배를 쓴다. 오케스트레이션 비용이 절감분을 상쇄할 위험이 크므로, 대규모 라벨링 전에 소규모 기준선 비교(3~5건)로 먼저 판단한다.

**기준선 파일럿 결과** (2026-10-01, 2차 개정 구조, `evaluation/pilot/` 4건)

조건: 기준선 = gpt-6-luna / high 단일 세션. Router = 메인 세션 gpt-6-luna / low + 단계 subagent(Router가 결정). 토큰은 입력+출력(캐시 입력 포함).

| 사례 | 기준선 | Router | 증가 | 시간 (기준선 → Router) |
|---|---:|---:|---:|---|
| L1 문자열 변경 | 123k | 573k | +368% | 18s → 77s |
| L2 함수 추가 | 528k | 952k | +80% | 95s → 142s |
| L3 여러 파일 | 347k | 1,389k | +301% | 91s → 203s |
| L4 인증 | 326k | 1,171k | +259% | 77s → 269s |
| 합계 | 1.32M | 4.08M | +209% | 281s → 691s |

- 8회 모두 테스트 통과, Router Review 4건 approved. 요구사항 충족 표시(`baseline mark`)는 하지 않아 공식 판정은 `insufficient_data`지만, 사용량이 줄지 않았으므로 §22.3 규칙상 `auto` 불가가 확정이다.
- Router 메인 세션만으로 361k~468k를 써서 4건 중 3건에서 기준선 작업 전체보다 많았다. 메인 세션을 빼도 subagent 합계가 기준선 이상이었다.
- 측정 도구 보완 필요: 실행 후 작업 디렉터리를 지워 diff가 남지 않음(요구사항 판정 불가), Router의 판정 레벨이 실행 기록에 남지 않음.

결론: 3차 개정에서 실행 구조를 요청 단위 라우팅 + cascade로 전환한다(§3).

**파일럿 재측정 결과** (2026-10-01, 3차 개정 구조 `mer`, 같은 4건, `runs/pilot-p7.jsonl`)

조건: 기준선 = gpt-6-luna / high 단일 세션. Router = `mer`(구독 분류기 1회 + 세션 + Test Gate + 승격 + 고위험 Review). "전체"는 입력+출력(캐시 입력 포함), "비캐시"는 캐시되지 않은 입력+출력.

| 사례 | 판정 | 기준선 전체 | Router 전체 | 기준선 비캐시 | Router 비캐시 | 시간 (기준선 → Router) |
|---|---|---:|---:|---:|---:|---|
| L1 문자열 변경 | L1, luna/medium | 92k | 181k | 25k | 32k | 15s → 31s |
| L2 함수 추가 | L2, luna/medium | 321k | 182k | 41k | 28k | 69s → 44s |
| L3 여러 파일 | L3, luna/high + 계획 먼저 | 499k | 1,017k | 40k | 103k | 123s → 132s |
| L4 인증 | **L2**(오판) + auth, luna/medium → 승격 luna/high, Review sol/high 2회 모두 changes_requested | 365k | 1,068k | 13k | 242k | 112s → 694s |
| 합계 | | 1.28M | 2.45M (+92%) | 118k | 404k | 319s → 902s |

- 8회 모두 테스트 통과, 저장된 diff 기준 요구사항 8건 모두 충족(`baseline mark` yes). 품질 4건 preserved. 판정: `do_not_default_to_auto`.
- 2차 구조(+209%)보다 나아졌지만 기준선보다 여전히 많다. 기준선보다 적은 것은 L2 1건뿐이다.
- 원인:
  1. **분류기 고정 비용**: 요청마다 입력 약 27k(비캐시 5~20k). L1 작업 전체 비용에 맞먹는다.
  2. **L3 계획 먼저 쓰기**: 같은 luna/high인데 기준선의 약 2배를 썼다. 계획 지침이 턴 수를 늘린다.
  3. **고위험 Review 루프**: L4 인증이 L2로 오판됐고, auth 신호로 붙은 sol/high Review가 두 번 모두 changes_requested를 내 승격 1회 + 재Review로 비용과 시간이 커졌다. 최종 diff는 기준선과 마찬가지로 요구사항을 충족했다. Review 본문은 기록되지 않아 무엇을 요구했는지는 확인할 수 없다.
  4. **절감 여지가 작다**: 현재 Codex에서 economy와 balanced가 같은 모델(gpt-6-luna)이라, 기준선(luna/high) 대비 Router가 줄일 수 있는 것은 effort(high → medium)뿐이다.
- 측정 도구: 저장 diff에 `__pycache__`가 섞여 있었다(평가 저장소 exclude에 추가해 수정). Gate는 lint/typecheck/build 명령이 없어 4건 모두 `incomplete`(test는 통과).
- 표본이 4건 × 1회라 분산이 크다(L1은 diff가 같은데 Router 세션만 153k 입력).

**측정 오류 정정 (2026-10-01)**: Codex 세션 안에서 모델이 사용자 전역 `~/.codex/AGENTS.md`(ECC 지침: "코드 수정 후 code-reviewer, 기능·버그 수정은 tdd-guide를 즉시 사용") 때문에 subagent(gpt-5.6-terra)를 스스로 만들고 있었다. 이 subagent의 rollout은 자기 `session_meta` 뒤에 부모의 `session_meta`를 복사해 두는데, `read_rollout`이 마지막 것을 읽어 부모(메인 세션)로 잘못 분류했다. 그 결과 기준선(exec 스트림을 메인으로 씀)은 subagent 사용량이 **빠졌고**, Router(rollout 합산)는 포함됐다. 첫 `session_meta`를 쓰도록 고쳤고(`evaluation/usage.py`), 위 표를 같은 rollout으로 재집계하면 기준선 1.78M, Router 2.45M(+38%)이다(`runs/pilot-p7.reagg.jsonl`).

**파일럿 v2 결과** (2026-10-01, 분류기 Jev → 실패 시 subscription, L3 계획 먼저 제거, Review 반복 제거, 4건 × 2회, 정정된 집계, `runs/pilot-p7b.reagg.jsonl`)

| 사례 | Jev 판정 | 기준선 평균 | Router 평균 | 증감 |
|---|---|---:|---:|---:|
| L1 문자열 변경 | L2 | 253k | 108k | −58% |
| L2 함수 추가 | L2 | 463k | 155k | −66% |
| L3 여러 파일 | L3 + 위험 신호(Jev, 정규식은 없음) → 계획 먼저 + sol/high Review | 585k | 1,232k | +111% |
| L4 인증 | L3 + auth → 계획 먼저 + sol/high Review | 765k | 1,036k | +35% |
| 합계 (8쌍) | | 4.13M | 5.06M | +22% |

- 16회 모두 테스트 통과, 요구사항 16건 충족(저장 diff 확인). 품질 8쌍 모두 preserved. Router Review 4건 모두 changes_requested(승격·재Review 없이 종료). 판정: `do_not_default_to_auto`.
- Jev는 8회 모두 성공(fallback 없음), 호출당 입력 567~627 / 출력 119 토큰.
- **위험 신호가 없는 작업(L1·L2)에서는 Router가 기준선보다 58~66% 적다.** 세션 하나를 luna/medium으로 돌리고, 모델이 subagent를 만들지 않았다(기준선은 L1·L2 4회 중 3회 code-reviewer subagent를 만들었다).
- **위험 신호가 붙은 작업(L3·L4)에서는 많다.** 구현 세션이 tdd-guide·code-reviewer subagent를 만들고, mer의 독립 Review 세션이 다시 code-reviewer subagent를 만들어 리뷰가 중복된다(L3·L4 Router run당 subagent 2~3개, 기준선 1~2개).
- 사용자 전역 AGENTS.md는 두 모드에 똑같이 적용되므로 비교는 공정하지만, 이 지침이 없는 환경에서는 숫자가 크게 달라진다.

**파일럿 v3 결과** (2026-10-01, v2 + 독립 Review는 L4·L5에만, 4건 × 2회, `runs/pilot-p7c.jsonl`, 보고서 `runs/pilot-p7c-report.md`)

| 사례 | Jev 판정 | 기준선 평균 | Router 평균 | 증감 |
|---|---|---:|---:|---:|
| L1 문자열 변경 | L2 | 238k | 123k | −48% |
| L2 함수 추가 | L2 | 448k | 156k | −65% |
| L3 여러 파일 | L3 + 위험 신호 → 계획 먼저 | 571k | 681k | +19% |
| L4 인증 | L3 + auth → 계획 먼저 | 580k | 505k | −13% |
| 합계 (8쌍) | | 3.67M | 2.93M | **−20%** |

- 판정: **`auto_allowed`** (품질 8쌍 모두 preserved, 전체 사용량 감소). 시간도 합계 174초 짧다. 16회 모두 테스트 통과, 요구사항 충족. Jev 8회 모두 성공(fallback 없음). 독립 Review는 붙지 않았다(Jev가 L4 인증 작업을 L3로 판정).
- L4 인증 경계 사례: 비ASCII 서명을 넣으면 `TypeError`가 나는 구현이 기준선 2회 중 1회, Router 2회 중 2회였다(요구사항의 "malformed"를 엄격히 보면 미흡, 두 모드 공통 수준).
- 한계: 4건 × 2회의 작은 표본이고 회차 간 편차가 크다(기준선 L1이 91k~383k). 사용자 전역 ECC 지침이 있는 환경 기준이다. L4 작업이 L3로 판정되면 독립 Review가 빠진다.
- 측정 도구: 같은 이름의 diff가 다음 파일럿에 덮어쓰였다(v2 diff는 판정 후 덮어써짐). diff를 `<out>-diffs/` 디렉터리에 저장하도록 고쳤다.

**파일럿 v4 결과** (2026-10-01, v3 + auth·security Review, Jev 대상 판정, 150건 기준 위험 임계값, frontier gpt-6.1-sol, `runs/pilot-p7d.jsonl`)

| 사례 | Jev 판정 | 기준선 평균 | Router 평균 | 증감 |
|---|---|---:|---:|---:|
| L1 문자열 변경 | L2 | 123k | 139k | +13% |
| L2 함수 추가 | L2 | 646k | 156k | −76% |
| L3 여러 파일 | L3 | 376k | 654k | +74% (회차별 −3%, +308%) |
| L4 인증 | L3 + auth → Review(gpt-6.1-sol) | 545k | 1,332k | +145% |
| 합계 (8쌍) | | 3.38M | 4.56M | **+35%** |

- 판정: `do_not_default_to_auto`. 품질 8쌍 모두 preserved, 16회 모두 테스트 통과·요구사항 충족. Jev 8회 모두 성공.
- 증가분의 대부분은 L4 인증의 독립 Review다. Review 세션(209k, 282k)이 사용자 전역 ECC 지침대로 code-reviewer subagent(198k, 213k)를 또 만들어, Review 1회가 약 0.4~0.5M이다. Review는 1회 approved, 1회 changes_requested(비ASCII 서명 `TypeError` 경계 결함이 남은 쪽; 승격 없이 종료해 수정되지 않음).
- L3는 회차 간 편차가 크다(기준선 r2가 186k로 낮음). v3과 v4의 L3 Router(681k, 654k)는 비슷하다.
- 다음 조치: Review 세션이 subagent를 만들지 않도록 Review 프롬프트에 명시하고 L4 인증만 재측정한다.

**L4 인증 재측정** (2026-10-01, Review 프롬프트에 subagent 금지 추가, 2회, `runs/pilot-p7e-l4.jsonl`)

- Review 세션 비용: 0.4~0.5M → **138k, 175k**. Review 세션은 subagent를 만들지 않았다.
- Router 합계 1,247k / 1,219k(평균 1.23M), 기준선 1,010k / 646k(평균 0.83M) → +49%. 남은 차이는 구현 세션이 ECC 지침대로 만드는 code-reviewer·python-reviewer subagent(286k, 482k)와 회차 편차다. 기준선도 subagent를 만든다.
- 두 Review 모두 changes_requested였고, 4개 결과물(기준선 2, Router 2) 모두 비ASCII 서명에서 `TypeError`가 나는 같은 경계 결함이 있다. Review가 찾은 결함이 승격 없이 끝나 반영되지 않는다. → 조치(2026-10-01): changes_requested면 같은 구현 세션에서 지적 반영 1턴(재Review 없음).
- v4의 L1~L3와 이 L4를 합치면 기준선 1.97M, Router 2.18M(+11%)이다(서로 다른 실행을 합친 값이라 참고용).

**L4 인증 재측정 2** (2026-10-01, Review 지적 반영 1턴 추가, 2회, `runs/pilot-p7f-l4.jsonl`)

- 두 Router 실행 모두 Review가 changes_requested → 반영 1턴 → `review_fixed`. **두 결과물 모두 비ASCII 서명 결함이 고쳐졌다**(기준선은 2회 중 1회 남음).
- 비용: Router 1,097k / 998k(평균 1.05M), 기준선 771k / 470k(평균 0.62M) → +69%. 구현 세션 자체(613k, 631k)는 기준선과 비슷하고, 차이는 Review 세션(171k, 174k)과 반영 턴, 반영 턴에서 ECC 지침으로 생긴 python-reviewer subagent(135k)다. 반영 지시에도 subagent 금지를 추가했다.
- Review 세션은 더 이상 subagent를 만들지 않았다.
- 정리: auth·security·L4 이상 작업에서 Router는 기준선보다 비싸지만 품질이 더 좋다(결함 수정). L1·L2에서는 크게 싸다. 기본 모드 결정은 더 큰 파일럿 세트(코퍼스에서 10건 안팎)로 한다.

**결정 (2026-10-01)**: 기본 모드는 `auto`로 유지한다(Phase 7 완료 조건). 단 v3에서 L4 인증 작업이 L3로 판정돼 독립 Review가 빠졌으므로, L1~L3에서도 auth·security 신호가 있으면 독립 Review를 붙인다(§11.4). 이 조건은 L4 인증 사례에 Review 세션 1회를 더하므로, 표본을 늘린 재측정(코퍼스, 반복 횟수)에서 절감 폭을 다시 확인한다.

**파일럿 세트 v2 결과** (2026-10-01, 13건 × 2회 계획, `evaluation/pilot/cases-v2.jsonl`, `runs/pilot-v2.jsonl`, 보고서 `runs/pilot-v2-report.md`)

1회차 도중 Codex 워크스페이스 크레딧이 소진됐다(rollout: `usage_limit_exceeded`, "Your workspace is out of credits"). 그래서 L5 Router 1회차와 2회차 26회 전체가 약 3초 만에 실패했다. 유효한 쌍은 1회차 12건(L5 제외)이다. 2회차의 Jev 분류는 실패 전에 끝났으므로 판정 기록은 남아 있다.

| 사례 | 라벨 | Jev 판정 (r1 / r2) | 기준선 | Router | 증감 | subagent (기준선 / Router) |
|---|---|---|---:|---:|---:|---|
| l1 문구 변경 | L1 | L2 / L2 | 92k | 185k | +101% | 0 / 0 |
| l1b 상수 변경 (auth.py) | L1 | L1 / L1, auth → Review approved | 341k | 285k | −17% | 1 / 0 |
| l2 restock | L2 | L2 / L2 | 527k | 125k | −76% | 1 / 0 |
| l2b qty TypeError | L2 | L2 / L2 | 441k | 420k | −5% | 1 / 1 |
| l2c 모르는 필드 무시 | L2 | L2 / L2 | 828k | 402k | −51% | 2 / 1 |
| l2d 원자적 저장 (data_loss) | L2 | L2 / L2 | 827k | 469k | −43% | 2 / 1 |
| l3 할인 (여러 파일) | L3 | L3 / L3 | 467k | 941k | +101% | 1 / 2 |
| l3b 환불 (payment) | L3 | L2 / L2 | 896k | 156k | −83% | 2 / 0 |
| l3c 저장 형식 v2 (data_migration) | L3 | L3 / L3 | 999k | 496k | −50% | 3 / 1 |
| l3d 동시성 (concurrency) | L3 | L4 / L4, sol/high + Review approved | 937k | 1,098k | +17% | 1 / 3 |
| l4-auth 토큰 만료 | L4 | L3 / L3, auth → Review changes_requested → review_fixed | 830k | 992k | +19% | 1 / 2 |
| l4b PriceRule 파이프라인 | L4 | L4 / **L3**, sol/high + Review changes_requested → review_fixed | 764k | 1,540k | +102% | 1 / 4 |
| l5 키 회전 | L5 | L5 / L5 | 3,497k | (실패) | | 3 / – |
| 합계 (12쌍) | | | 7.95M | 7.11M | **−11%** | 16 / 15 |

- 품질: 12쌍 중 preserved 11, improved 1(l4-auth). 24개 결과물 모두 fixture 복사본에 diff를 적용해 테스트를 통과했다. 요구사항은 저장 diff를 읽어 판정했다.
- l4-auth 기준선은 비ASCII 서명(`ann.1000.é`)에서 `PermissionError` 대신 `TypeError`가 난다. "malformed 토큰은 invalid token" 요구에 어긋나므로 미충족으로 판정했다. Router 결과물은 Review 반영 턴에서 이 결함이 고쳐졌다(v4 이후 3회 연속 같은 결과).
- l5 기준선은 요구사항을 충족한다. 다만 비ASCII 서명, 짝 없는 surrogate, `None` 입력에서 `PermissionError`가 아닌 예외가 난다. fixture 원본에 이미 있던 결함이고 L5 요구사항에 malformed 처리가 없어 충족으로 판정했다. L5 기준선 한 건이 3.5M으로 가장 비싸다.
- 판정: 도구 판정은 `insufficient_data`(실패 실행 제외 때문). 유효 12쌍만 보면 품질을 유지하면서 전체 사용량이 11% 줄어 §22.3의 `auto` 조건을 만족한다.
- 비용 구조는 이전 파일럿과 같다.
  - L1·L2·위험 신호만 있는 L3에서는 싸다. 9건 중 7건 감소, 큰 폭은 −43~−83%다.
  - sol 승격이나 독립 Review가 붙는 작업은 비싸다(+17~+102%).
  - l1(+101%)은 diff가 기준선과 같은데 Router 세션 입력이 2배다. 1회 표본의 회차 편차로 본다.
- 사용량 차이의 상당 부분은 ECC 전역 지침으로 생기는 subagent 수와 함께 움직인다. Router가 effort를 낮춘 세션은 subagent를 덜 만들고, sol/high 세션은 더 만든다(l4b Router 4개). 라우팅 효과와 subagent 효과가 섞여 있다.
- 분류:
  - Jev 레벨은 1회차 13건 중 8건이 라벨과 일치했다.
  - 낮게 본 것: l3b(payment) → L2, l4-auth → L3.
  - 높게 본 것: l1 → L2, l3d → L4.
  - l4b는 같은 입력에 1회차 L4, 2회차 L3으로 판정이 갈렸다.
  - 위험 신호가 auth Review를 붙여 l4-auth 결함을 고쳤다. l1b에서는 상수 변경에 Review가 붙어 비용이 들었다(그래도 기준선보다 적음).

**결정 유지 (2026-10-01)**: 기본 모드 `auto`를 유지한다. 근거는 세 가지다.
- 4건 파일럿의 +22%·−20%·+35%와 달리, 12건 표본에서 −11%이고 품질 저하가 없다.
- auth 작업에서 결함 수정이 반복 확인됐다.
- 남은 확인 사항: L5 Router(크레딧 소진으로 미측정), 2회차 반복(회차 편차).

**파일럿 세트 v2 2회차** (2026-10-02, 같은 13건 × 1회, `runs/pilot-v2b.jsonl`, 보고서 `runs/pilot-v2b-report.md`)

- 26회 모두 성공했다. 26개 결과물 모두 diff 적용 후 테스트를 통과했다.
- 품질은 preserved 12, improved 1(l4-auth)이다. 기준선 l4-auth는 다시 비ASCII 서명 `TypeError`, surrogate `UnicodeEncodeError`, `None` 입력 `AttributeError`가 났다. Router는 Review 반영 후 모두 `PermissionError`였다.
- L5 Router 첫 측정: sol/xhigh, Review approved, 2.60M(기준선 1.41M, +85%), 798초, subagent 5개. 결과물은 malformed 입력을 모두 `PermissionError`로 처리했다. 기준선은 v2와 같은 원본 결함이 남았다(요구사항 밖이라 둘 다 충족).
- 2회차 합계: 기준선 7.26M, Router 8.06M(**+11%**). 도구 판정은 `do_not_default_to_auto`다.
- Jev 판정은 l4b(L3)를 빼고 1회차와 같았다.

**v2 합산** (1회차 유효 12쌍 + 2회차 13쌍 = 25쌍, `runs/pilot-v2-combined.jsonl`, `runs/pilot-v2-combined-report.md`)

| 묶음 | 기준선 | Router | 증감 |
|---|---:|---:|---:|
| sol 승격·독립 Review 없음 (l1, l2 4건, l3, l3b, l3c; 16쌍) | 9.31M | 5.42M | −42% |
| sol 승격 또는 Review (l1b, l3d, l4-auth, l4b, l5; 9쌍) | 5.90M | 9.74M | +65% |
| 합계 (25쌍) | 15.21M | 15.17M | **−0.3%** |

- 도구 판정은 `auto_allowed`(품질 23 preserved, 2 improved, 전체 감소)지만 감소폭 0.3%는 회차 편차 안이다. 시간은 Router가 합계 721초 길다. subagent 수는 기준선 28, Router 29로 같다.
- 지금까지 파일럿 증감: +22%, −20%, +35%, −11%(v2 1회차), +11%(v2 2회차), 합산 −0.3%. **전체 비용 절감은 확인되지 않았다.**
- 확인된 것:
  - 위험 없는 L1~L3는 기준선보다 약 40% 싸다.
  - auth 작업에서 Review 반영으로 결함이 고쳐진다(4회 연속).
  - sol 승격·Review는 약 65% 비싸다.
- Router는 비용을 낮은 단계에서 아껴 높은 단계의 검증에 쓰는 구조다. 총비용은 기준선과 비슷하고 auth·보안 작업의 품질은 더 좋다.

**실제 기본값 기준선** (2026-10-02, `runs/pilot-v3-sol-baseline.jsonl`, 짝 `runs/pilot-v3-sol-paired.jsonl`, 보고서 `runs/pilot-v3-sol-report.md`)

위 파일럿의 기준선 gpt-6-luna/high는 사용자의 실제 Codex 기본값이 아니었다. 실제 기본값은 `~/.codex/config.toml` 기준 gpt-6.1-sol/medium이다. 그래서 기준선만 실제 기본값으로 다시 돌렸다(`live_runner --modes baseline`, 13건 × 2회). 이번에도 크레딧이 소진돼 유효 실행은 14회다(1회차 l3c 제외 12건, 2회차 l1·l2). 짝은 이렇게 맞췄다.
- 1회차 기준선은 v2 2회차 Router와 짝지었다.
- 2회차 기준선은 v2 1회차 Router와 짝지었다.

| 묶음 | 기준선 (sol/medium) | Router | 증감 |
|---|---:|---:|---:|
| 합계 (14쌍) | 10.69M | 7.87M | **−26%** |
| 위험 없는 L1~L3 (l1 ×2, l2 ×2, l2b, l2c, l2d, l3, l3b) | | | −83~+18%, 9쌍 중 8쌍 감소 |
| sol 승격·Review (l3d, l4b, l5) | | | +32~+37% |
| l1b, l4-auth (luna + auth Review) | | | −11%, −25% |

- 도구 판정은 `auto_allowed`다. 품질은 14쌍 모두 preserved, 14개 기준선 결과물 모두 테스트를 통과했고 요구사항을 충족했다.
- sol 기준선은 l4-auth와 l5에서 비ASCII 서명, surrogate, `None` 입력을 모두 `PermissionError`로 처리했다. luna 기준선 대비로 보였던 Router의 "품질 개선"은 실제 기본값 대비로는 없다. 대신 Router는 같은 품질을 더 적은 토큰으로 낸다.
- 시간은 Router가 합계 487초 길다. L5의 sol/xhigh와 auth Review 때문이다.
- 이 지표는 토큰 수만 더한다. Router 토큰의 대부분은 sol보다 싼 luna 세션이므로 실제 비용 절감폭은 −26%보다 클 것으로 본다. 단가 비율은 측정하지 않았다.

**결정 (2026-10-02)**: 기본 모드 `auto`를 유지한다. 근거는 실제 기본값(gpt-6.1-sol/medium) 대비 토큰 −26%, 품질 동일이다. 남은 개선 대상은 sol 승격·Review 경로(+32~+37%)다.

**과승격 규칙 (2026-10-02)**: 파일럿의 l3d(라벨 L3, concurrency)가 Jev 판정 L4로 sol/high 세션과 Review를 받아 기준선보다 32~48% 비쌌다. 원인은 위험 신호가 아니라 Jev의 레벨 판정이다. 코퍼스 150건을 다시 돌려 레벨 확률 분포를 기록했다(`runs/compare-v1-jev-dist.json`, Jev 150회).
- Jev가 L4·L5로 본 작업 중 라벨이 L1~L3인 10건은 P(L4)+P(L5)가 0.50~0.75였다. 라벨이 L4·L5인 작업은 0.65~1.00이었다.
- concurrency 신호가 있으면 분리가 더 뚜렷하다. 라벨 L3는 0.51~0.75, 라벨 L4·L5는 0.85 이상이었다.
- 규칙(`difficulty/jev.py`):
  - L4·L5 판정이어도 P(L4)+P(L5)가 0.6 미만이면 L3로 낮춘다.
  - concurrency 신호가 있으면 기준을 0.8로 올린다.
  - 낮춘 경우 reason code `jev_l4_unsure`를 남기고, 분포는 그대로 둔다.
- 코퍼스 결과:

  | 지표 | 전 | 후 |
  |---|---:|---:|
  | 라벨 L1~L3를 L4 이상으로 본 수 | 10 | 4 |
  | 정확 일치 | 107/130 | 113/130 |
  | 라벨 L4·L5를 L3 이하로 본 수 | 1 | 1 (규칙과 무관한 exp-069) |

- 한계:
  - 같은 150건으로 정한 값이라 과적합 위험이 있다.
  - concurrency 기준 0.8과 라벨 L4·L5 최저값 0.85의 여유가 작다.
  - Jev는 같은 입력에도 회차마다 레벨이 바뀐다(두 번의 150건 실행에서 5건).

**측정 A: 과승격 규칙만** (2026-10-02, Router 13건 × 1회, `--subagent-policy codex`, `runs/pilot-v4a-router.jsonl`, sol 기준선 1회차와 짝 `runs/pilot-v4a-report.md`)
- 판정이 의도대로 바뀌었다. l3d는 L4에서 L3로, l4b는 L4·L3에서 L3로 내려갔다. l4-auth(L3+auth)와 l5(L5)는 그대로다.
- 13건 모두 테스트를 통과했고 요구사항을 충족했다. l4-auth는 Review 반영 후 malformed 입력을 모두 `PermissionError`로 처리했다. l5는 surrogate 입력에서 `UnicodeEncodeError`가 남았다(요구사항 밖이라 충족으로 판정).
- l3d는 1,145k에서 999k(−13%), l4b는 1,233k에서 1,116k(−9%)로 줄었다(이전 Router 2회 평균 대비). 둘 다 아직 sol 기준선(904k, 687k)보다 많다. luna/high 세션이 subagent를 1~2개 만들었다.
- 12건 합계는 이전 Router 8.39M, 측정 A 8.27M(−1.4%)으로 같은 수준이다. 같은 레벨에서도 건별 편차가 크다(l3b L2: 156k → 487k).
- sol 기준선 대비 −14%(9.64M → 8.27M)이고, 판정은 `auto_allowed`다.
- 정리: 과승격 규칙은 비싼 경로(sol + Review)를 없앴지만 1회 측정의 절감폭은 편차 안이다. 남은 비용은 레벨과 무관하게 subagent에서 나온다. 다음은 측정 B(subagent 정책)다.

**측정 B: 과승격 규칙 + subagent 정책** (2026-10-02, Router 13건 × 1회, `--subagent-policy level`, `runs/pilot-v4b-router.jsonl`, 보고서 `runs/pilot-v4b-report.md`)
- 정책이 그대로 지켜졌다. subagent는 L1~L4 12건 모두 0개, L5는 1개였다(측정 A: 합계 15개).
- 토큰: 13건 합계 측정 A 9.01M에서 측정 B 2.84M(**−68%**)으로 줄었다. 건별로 −9~−88%이고, 시간도 대부분 줄었다(l3d 193초 → 31초).
- sol 기준선과 짝지은 12건: 9.64M → 2.57M(**−73%**).
- 품질:
  - 13건 모두 테스트를 통과했다. l4-auth는 Review 반영으로 malformed 입력을 모두 처리했고, l5는 테스트 15개로 요구사항을 모두 덮었다.
  - 결함 2건이 나왔다.
    - **l3d**: 동시성 테스트가 경쟁 상태를 잡지 못한다. 락을 뺀 원본 코드에서 20회 모두 통과한다. 측정 A·v2b의 l3d 테스트는 같은 조건에서 20회 모두 실패했다(인터리빙을 강제함). 테스트가 검증 역할을 못 하므로 요구사항 미충족으로 판정했다.
    - **l3**: 할인율이 잘못되면 재고를 줄인 뒤 `ValueError`를 낸다. 요구사항에 명시되지 않아 충족으로 판정했지만 이전 결과물들(할인 계산을 재고 차감 전에 함)보다 나쁘다.
  - 도구 판정은 `do_not_default_to_auto`(regressed 1건)다.
- 해석: ECC 지침의 subagent(tdd-guide, code-reviewer)는 비용의 대부분이었지만, 테스트 강도와 부작용을 잡는 검증도 했다. 두 결함 모두 L3·위험 신호(l3d concurrency) 또는 위험 신호 없음(l3)에서 독립 Review가 없는 경로였다.
- 1회 측정이라 편차가 크다. 결함 2건이 정책 탓인지 회차 편차인지는 반복 측정으로 확인해야 한다.

**보완책 (2026-10-02)**: subagent를 끈 구현 세션(L1~L4, `level` 정책)에 검증을 싸게 되돌린다.
- concurrency·data_loss 신호가 있는 L1~L3도 독립 Review를 받는다. 기존에는 auth·security만 받았다. Review 프로필은 기존 floor를 따른다: concurrency는 sol/high, data_loss는 sol/xhigh. `codex` 정책과 조언 hook(사용자의 대화형 세션은 subagent가 켜져 있음)은 기존대로다.
- 구현 프롬프트에 한 문장을 더한다: "새 테스트는 변경 전 코드에서 실패해야 하고(막으려는 경쟁 상태나 실패를 강제로 일으킨다), 상태를 바꾸기 전에 입력을 검증한다."
- Review 점검 항목에 "변경 없이도 통과하는 테스트"와 "오류 전에 바뀐 상태"를 추가했다.

**측정 B': 보완책 적용** (2026-10-02, Router 13건 × 1회, `runs/pilot-v4c-router.jsonl`, 보고서 `runs/pilot-v4c-report.md`)
- 보완책은 의도대로 동작했다.
  - l3d는 concurrency 신호로 sol/high Review를 받았고(approved), 동시성 테스트가 락을 뺀 코드에서 20회 모두 실패한다.
  - l3는 잘못된 할인율에서 재고를 바꾸지 않는다.
  - l3b·l2·l3c 테스트가 "실패 시 상태 불변"을 확인한다.
  - l4-auth와 l5는 malformed 입력을 모두 `PermissionError`로 처리한다. l5의 surrogate 결함도 이번에는 없다.
- 새 결함 1건: **l1**. 모델이 도구를 한 번도 호출하지 않고 "변경했다"고 답했다(파일 변경 없음, 47k). 테스트는 원래 코드로도 통과하므로 mer는 `ok`로 끝냈다. 요구사항 미충족으로 판정했다. 프롬프트 보완책과 무관한 실패이고, mer가 빈 diff를 잡지 못하는 것이 문제다.
- 토큰:

  | 묶음 | sol 기준선 | A | B | B' |
  |---|---:|---:|---:|---:|
  | 12쌍 | 9.64M | 8.27M | 2.57M | 3.43M |

  - B' vs sol 기준선: **−64%**. B' vs A: −58%.
  - 보완책 비용은 B 대비 +0.86M이고, 대부분 l3d Review(+252k)와 L5(+346k)다.
- 도구 판정은 `do_not_default_to_auto`(regressed 1건, l1 빈 변경)다.
- 다음: 구현 대상(`route`)인데 구현 세션 뒤 diff가 비면 같은 세션을 한 번 재개해 변경을 요구하고, 그래도 비면 `no_changes`(exit 1)로 끝낸다.

**측정 v4d: 현재 구성 반복** (2026-10-02, 과승격 규칙 + subagent 정책 + 보완책 + 빈 변경 감지, Router 13건 × 2회, `runs/pilot-v4d-router.jsonl`, 보고서 `runs/pilot-v4d-report.md`)
- 26회 모두 변경이 있었고 테스트를 통과했으며 요구사항을 충족했다.
- 경계 검사도 2회 모두 통과했다.
  - l3d: 동시성 테스트가 락을 뺀 코드에서 20회 모두 실패한다.
  - l3: 잘못된 할인율에서 재고를 바꾸지 않는다.
  - l4-auth·l5: 비ASCII 서명, surrogate, `None`, 빈 문자열, 정수 입력을 모두 `PermissionError`로 처리한다.
- subagent: L1~L4 24회 모두 0개. L5는 1개와 2개였다. 동시 상한 1은 지켰고, 총 개수는 강제되지 않는다.
- 독립 Review: l4-auth(auth), l1b(auth), l3d(concurrency), l5(L5)에 붙었다. changes_requested는 반영 턴으로 모두 `review_fixed`가 됐다.
- 토큰 (건별 평균, sol 기준선이 있는 12건): sol/medium 9.62M → 3.82M(**−60%**).
  - 위험 없는 L1~L3: −62~−83%.
  - Review가 붙은 작업: −20~−54%.
  - L5: −40%.
- 도구 판정(sol 기준선과 짝지은 14쌍): **`auto_allowed`**. 품질은 14쌍 모두 preserved, 10.69M → 4.03M. 시간은 합계 222초 길다(Review와 L5 xhigh).

**모델별 비용 환산** (2026-10-02, `evaluation/cost.py`, 가격 `evaluation/prices.json`)
- 실행 기록의 스레드마다 rollout(본 세션, mer 세션, 모든 subagent)을 다시 읽는다. 누적 `total_token_usage`의 증가분을 직전 `turn_context`의 모델에 돌린다. 승격으로 세션 중간에 모델이 바뀌어도 맞게 나뉜다.
- Codex는 같은 `token_count`를 두 번 쓰기도 하므로 `last_token_usage`를 더하면 중복된다. 누적 증가분으로 계산한 합계는 40개 실행 모두에서 기록 합계와 정확히 같다.
- 가격은 OpenAI API 정가(USD/1M, 제3자 집계 사이트, 2026-10-02 확인)다. 구독 쿼터 가중치는 공개되지 않아 측정하지 않는다. Jev 분류 토큰은 별도 과금이라 토큰 수로만 남는다.

  | 모델 | 입력 | 캐시 입력 | 출력 |
  |---|---:|---:|---:|
  | gpt-6.1-sol | 2.00 | 0.10 | 10.00 |
  | gpt-6-luna | 0.10 | 0.01 | 0.50 |
  | gpt-5.6-terra | 2.00 | 0.20 | 12.00 |

- 결과: sol/medium 기준선 대비, 두 모드에 모두 있는 사례의 건별 평균 합계.

  | 측정 | 토큰 | USD |
  |---|---:|---:|
  | A (과승격 규칙만) | −30% | −70% |
  | B (+ subagent 정책) | −73% | −84% |
  | B' (+ 보완책) | −64% | −79% |
  | v4d (현재 구성, 2회) | −60% | **−78%** ($4.13 → $0.91, 12건) |

- 비용 차이는 토큰보다 크다. Router의 L1~L4 세션은 luna(sol의 1/20 단가)로 돌고, 기준선 subagent는 terra(sol급 단가)로 돈다. v4d에서 남은 비용의 대부분은 L5(sol/xhigh, $0.67)와 sol Review다.
- 참고: 초기 luna/high 기준선 대비 이전 Router(v2 합산)는 토큰 −19%, USD −6%였다. sol Review와 승격이 luna 절감분을 상쇄했다.

---

## 23. 패키징과 프로젝트 구조

시스템은 **2중 플러그인 구조**다.

1. 호스트에 설치되는 `Host Plugin` (Codex, Claude Code)
2. 난이도 판정기를 교체하는 `Difficulty Backend` (Subscription, Jev, Nimble, Future)

원칙:

- Core 로직은 한 곳에서 관리한다.
- 호스트별 플러그인에 같은 규칙을 따로 구현하지 않는다.
- 호스트별 차이는 Host Hook Adapter와 Host Adapter에서만 처리한다.
- Difficulty Backend는 Core의 registry로 교체한다.

저장소 구조(현재):

```text
model_effort_router/          Router Core (stdlib만 사용)
├── difficulty/               decision, base, registry, chain(fallback), risk, subscription, usage
├── policy/                   targeting, overrides, config, session(세션 프로필·사다리·위험 최소값), router
├── profiles/                 tier, effort
├── adapters/codex.py         tier/effort 매핑, 모델별 지원 effort
├── host/                     codex_hooks(조언 hook), advice, codex_exec(mer의 codex 호출)
├── gate/                     discovery, run (mer-gate)
└── logging/route_log.py      라우팅 로그, state_dir
(+ cli.py, flow.py, review.py: mer CLI)
plugins/codex-model-effort-router/
├── .codex-plugin/plugin.json manifest (hooks, skills 선언)
├── hooks/                    hooks.json, user_prompt_submit.py
├── bin/                      mer, mer-gate
├── skills/model-effort-router/SKILL.md   (조언·mer 사용법, 손으로 관리)
└── model_effort_router/      Core 복사본 (scripts/sync_plugin.py로 동기화, 테스트로 일치 검사)
evaluation/                   개발용 평가 도구 (플러그인에 포함하지 않음)
.agents/plugins/marketplace.json   로컬 marketplace
tests/                        unittest (live 호출 없음)
```

`jev.py`, `nimble.py`, `adapters/claude.py`는 해당 Phase에서 추가한다.

의존 방향:

```text
Difficulty Backend → DifficultyDecision → Stage Policy → Host Adapter
```

`policy/`는 개별 Backend 모듈을 직접 import하지 않는다.

---

## 24. 구현 순서

원칙: **Backend 하나 + 호스트 하나로 전체 흐름을 먼저 연결**한 뒤 확장한다.

구현 상태(2026-10-01):

| Phase | 상태 |
|---|---|
| 0 | 완료. 결과 문서: [phase0-host-api.md](../spikes/phase0-host-api.md) |
| 1–2 | 완료 (Opus 리뷰 승인) |
| 3 | 완료, Codex 설치 후 live 테스트로 전체 흐름 확인 (manifest·subagent 이름 버그 수정) |
| 4 | 도구 완료. 측정(라벨링, 기준선 비교)은 미수행 |
| 5–6 | 미착수 |
| 7 | 계획 (3차 개정 구조 전환, 아래) |

### Phase 0 — 호스트 API Spike (1일)

Codex에서 최소 플러그인으로 확인한다.

1. 플러그인 설치 후 일반 요청에서 자동으로 Router에 진입하는가.
2. 단계별 subagent에 지정한 모델·effort가 실제로 적용되는가(로그·트랜스크립트의 실제 모델로 확인).
3. 모델·effort를 실행 시점에 동적으로 넘길 수 있는가, 아니면 미리 정의한 조합에서 선택해야 하는가(§3.2).
4. Plan 결과, 변경 diff, Test 결과가 다음 단계로 전달되는가.
5. 구독 인증만으로 동작하고, timeout·취소·fallback에서 중복 실행이 생기지 않는가.
6. 구독 모델로 분류 호출이 가능하고 hook timeout 안에 끝나는가(§8.1).

완료 조건: 여섯 항목의 결과를 문서로 남기고 §3.2 표와 이 기획서를 갱신한다. 1·2가 불가능하면 제품 형태(§2) 자체를 재검토한다.

### Phase 1 — Contract + 단일 Backend

- `DifficultyBackend`, `DifficultyDecision`, L1~L5, Registry
- Subscription Backend (Phase 0 결과에 따라 다른 Backend로 대체)
- 규칙 기반 `risk_flags` 탐지
- Fallback과 기본 결정(L3)

완료 조건: Backend 결과가 `DifficultyDecision`으로 정규화되고, 실패 시 기본 결정이 나온다.

### Phase 2 — Stage Policy + Effort Map

- 레벨 기본값, 위험 신호 최소 프로필
- 라우팅 대상 판정
- Codex tier/effort 매핑, 모델별 지원 effort 처리

완료 조건: L1~L5와 risk_flags 조합마다 단계별 단일 프로필이 결정적으로 나온다.

### Phase 3 — Codex Vertical Slice

- Host Hook Adapter (자동 진입, 모드·override)
- 단계별 subagent 실행
- 단계 간 컨텍스트 전달
- Test Gate (명령 탐색, `not_run` 처리)
- 별도 컨텍스트 Review
- Fix loop (최대 2회), 단계 실행 상태 기록

완료 조건: 사용자가 Router를 호출하지 않아도 일반 작업 요청이 Plan → Implement → Test Gate → Review 순서로 완료된다.

### Phase 4 — 로그와 평가

- 라우팅 로그
- Routing Corpus 라벨 기준 문서와 초기 표본
- 비용 기준선 비교

완료 조건: Baseline 대비 품질·전체 사용량·완료 시간·재작업 횟수를 수치로 비교할 수 있다.

### Phase 5 — Claude Code Plugin (2026-10-02 개정)

Codex에서 측정으로 안정된 구조를 그대로 옮긴다. 구조는 조언 hook, `mer` CLI(분류 → 세션 → Test Gate → 승격 → 독립 Review → 반영 1턴), 레벨별 subagent 정책, 보완책, 빈 변경 감지다. 2차 개정의 "subagent 정의" 방식은 쓰지 않는다(§3.8). Core(분류, 위험 신호, 세션 정책, Gate)는 그대로 공유하고, 호스트별로 다른 것은 세 곳뿐이다.

**1. Host Adapter (`adapters/claude.py`)**: tier → 모델, 모델별 지원 effort(데이터로 관리).

| tier | 모델 | effort | API 정가 USD/1M (입력 / 캐시 / 출력) |
|---|---|---|---|
| economy | claude-sonnet-5-5 (2026-10-02 결정; Codex와 같이 balanced와 같은 모델이고 effort로 구분) | low~max | 2 / 0.20 / 10 |
| balanced | claude-sonnet-5-5 | low~max | 2 / 0.20 / 10 |
| frontier | claude-opus-5-5 (2026-10-02 결정) | low~max (API 기본 medium) | 4 / 0.20 / 20 |

참고: claude-haiku-4-5(1 / 0.10 / 5)는 effort를 지원하지 않는다. claude-fable-5-1(10 / 0.25 / 50)은 설정으로 바꿔 쓸 수 있게만 둔다.

- 지원 effort가 없는 모델(Haiku)을 설정으로 고르면 effort 플래그를 생략한다. 기존 규칙(가장 가까운 상위값)은 지원 목록이 비어 있을 때 적용할 수 없다.
- 가격은 `evaluation/prices.json`에 추가해 비용 환산을 그대로 쓴다.

**2. 세션 실행 (`host/claude_exec.py`, mer의 호스트 선택)**: Claude Code CLI 2.1.280에서 확인한 플래그로 `codex exec`를 대응시킨다.

| 역할 | Codex | Claude Code |
|---|---|---|
| 구현 | `codex exec -s workspace-write -m M -c model_reasoning_effort=E` | `claude -p --output-format json --model M [--effort E] --permission-mode auto` |
| 재개(승격·반영·빈 변경) | `codex exec resume <id>` | `claude -p --resume <session_id> --model M [--effort E]` |
| 독립 Review(읽기 전용) | `-s read-only` | `--permission-mode dontAsk --allowedTools Read,Grep,Glob` |
| subagent 끄기 | `-c agents.enabled=false` | `--disallowedTools Agent` |
| subagent 동시 1개(L5) | `-c agents.max_concurrent_threads_per_session=1` | 강제 수단 없음: 프롬프트 지시만 |
| 사용량 | `--json` 스트림 + rollout | `--output-format json`의 `usage`·`session_id`(필드 이름은 live 확인 필요) |

- 구현 세션의 권한 모드는 `auto`다(2026-10-02 결정). 분류기 기반 자동 승인으로 Codex workspace-write와 가장 가깝다. 안전 우회 플래그(`bypassPermissions`)는 쓰지 않는다.
- 분류기 재귀 방지: mer의 세션에는 `MER_CLASSIFIER=1`을 두고, hook은 이 값을 보면 아무것도 하지 않는다(Codex와 같음).

**3. 플러그인 패키지 (`plugins/claude-model-effort-router/`)**: `.claude-plugin/plugin.json`, `hooks/hooks.json`(UserPromptSubmit 조언 hook, 출력은 `hookSpecificOutput.additionalContext`), `bin/mer`, `bin/mer-gate`, skill. Core 복사본은 `scripts/sync_plugin.py`로 동기화한다. 로컬 marketplace에 등록한다.

**분류기**: 기본은 Jev(호스트와 무관)다. subscription fallback은 호스트의 CLI를 쓰도록 바꾼다. Claude에서는 `claude -p --model claude-haiku-4-5`이고, Codex가 없는 환경에서 `codex exec`를 부르지 않게 한다.

**구현 상태 (2026-10-02, 단위 테스트까지; live 확인 전)**: `adapters/claude.py`, `host/claude_exec.py`(argv, 결과 파싱, 호출별 사용량), `host/hosts.py`(`--host codex|claude`, 없으면 `MER_HOST`, 없으면 codex), host 인식 subscription 분류기(`claude -p --model claude-haiku-4-5 --permission-mode dontAsk --tools ""`), `plugins/claude-model-effort-router/`, 루트 `.claude-plugin/marketplace.json`, `scripts/sync_plugin.py`의 두 번들 동기화, `evaluation/prices.json`의 Claude 가격. 평가 도구(`live_runner`, `cost.py`)의 Claude 지원은 아직 없다: live_runner는 `--host`를 mer에 넘기고 `codex exec` 기준선 명령을 `claude -p`로 바꿔야 하고, rollout 대신 mer가 보고한 호출별 사용량(`calls[].usage`)을 써야 하며, cost.py는 rollout의 모델별 사용량 대신 그 호출 기록의 모델을 써야 한다.

**검증 순서**:
1. 단위 테스트(모델 호출 없음).
2. live 확인(사용자 승인 후): `--output-format json` 응답 형태, `--resume`에서 모델·effort 변경, `--disallowedTools Agent` 효과, 권한 모드에서 Gate 명령 실행.
3. 파일럿 13건으로 기준선(사용자의 Claude Code 기본 모델) 대비 측정. 지표는 Codex와 같다(품질, 토큰, 금액).

완료 조건: 같은 Router Core로 Claude Code에서 `mer run`이 Codex와 같은 흐름으로 동작하고, 파일럿에서 품질을 유지한다.

**live 확인 (2026-10-03, Claude Code 2.1.285, `evaluation/probes/claude_live_probe.sh`)**:
- 동작이 확인된 것:
  - 결과 JSON 형태
  - 호출 단위 `usage`
  - 재개 시 세션 id 유지와 모델·effort 전환
  - `auto` 모드에서 확인 질문 없는 명령 실행
  - `--disallowedTools Agent`로 subagent 도구 제거
  - 읽기 전용 Review의 수정 불가
  - 격리된 분류기 호출(약 3.2초, Haiku 입력 3.7k)
  - pilot-l1의 `mer run --host claude` 성공(Sonnet 5.5/medium, 167k 토큰, 정확한 diff와 테스트)
- Claude Code 2.1.280은 `claude-sonnet-5-5`를 모른다. 최신 Claude Code가 필요하다.
- `total_cost_usd`와 `modelUsage`는 세션 누적값이고, 세션 시작 시의 Haiku 부수 호출은 `usage`에 없다. 비용 환산은 세션별 마지막 `total_cost_usd`로 한다.
- 남은 것: 승격 경로(파일럿에서 승격 0회). 상세는 `plugins/claude-model-effort-router/README.md`.
- 플러그인 설치(2026-10-03, user scope): hook이 개발 요청에 `[model-effort-router] Advisory only ...` 조언을 대화에 넣는 것을 확인했다. subagent 보고 같은 비사용자 메시지도 분류되는 오분류가 있다.

**파일럿 (2026-10-03, 13건 × 1회, Jev, subagent 정책 level, `runs/pilot-c1r*`, `runs/pilot-c1-opus*`)**:
- Claude Code 기본 모델은 Sonnet 5.5였고, 기준선은 subagent를 쓰지 않았다.
- Sonnet 기준선 대비 라우터: 토큰 +17%, USD +74%($3.13 → $5.44). 기준선이 이미 economy 단계와 같은 모델이라 내릴 곳이 없고, 리뷰·L5 비용만 더해진다.
- Opus 기준선(`--baseline-model claude-opus-5-5`) 대비 라우터: USD −5%($5.72 → $5.44). L5를 빼면 −35%, Sonnet medium으로 간 6건은 −54%. 위험 표시 리뷰 3건은 ±0%. L5 한 건(Opus xhigh + 리뷰 후 수정)이 $2.07로 Opus 단독($0.56)의 3.7배였다.
- 품질: 저장된 diff 25건(Sonnet 기준선 중 14건은 `.omc/` 경합으로 diff 유실, 수정됨)을 다시 적용하면 모두 테스트를 통과한다.
- 조치: Claude adapter의 xhigh를 high로 매핑했다. L5 구현·리뷰와 data_loss 리뷰가 Opus high가 되고, high→xhigh 승격 단계는 같은 profile 재시도가 된다.
- 조치 후 L5 재실행(`runs/pilot-c1-l5*`): Opus high, 리뷰 approved(지적 3건, 수정 없음), $0.99(이전 $2.07, Opus 단독 $0.56), 테스트 통과. 계획·구현·리뷰 세션마다 약 20만 토큰의 고정 맥락이 붙어 단독 실행보다 여전히 비싸다. 이 값으로 바꾸면 라우터 합계는 Opus 기준선 대비 −24%, Sonnet 기준선 대비 +39%다.
- 고정 맥락 축소(`session.claude_context`, 기본 lean, 2026-10-03):
  - 1차 lean(`--setting-sources project,local`)은 첫 호출 캐시 쓰기를 31.6k → 5.1k로 줄였고 L5는 $0.70(승인)이었지만, `~/.claude/rules`까지 빠져 폐기했다.
  - 현재 lean: 구현·재개 세션은 모든 설정을 읽고 켜진 플러그인만 `--settings {"enabledPlugins": {id: false}}`로 끄며 MCP를 뺀다. 읽기 전용 세션은 user 설정만 읽고 hook을 모두 끈다.
  - 프로브(7·8단계): 사용자 규칙 11개 파일과 프로젝트 CLAUDE.md가 읽히고, 플러그인 8개가 꺼졌으며(남은 skill 목록은 사용자 `~/.claude/commands`·`skills`와 claude.ai 조직 skill), 첫 호출 캐시 쓰기는 31.6k → 21.8k(−31%). 읽기 전용 세션에서 project/local hook과 `--settings` hook이 실행되지 않았다.
  - L5 재측정(`runs/pilot-c1-l5-lean2*`): 리뷰 changes_requested 후 수정까지 가서 $1.55, 테스트 통과. 리뷰 결과에 따라 세션 수가 달라져 단일 실행으로는 lean 효과를 판단할 수 없다. 2회 더 돌린 3회: $1.55·$1.22(둘 다 수정 요청 후 수정), $0.84(승인), 평균 $1.20, 모두 테스트 통과. 승인된 실행끼리 보면 full $0.99 → lean $0.84(−15%). L5 라우터는 Opus 단독($0.56)의 1.5~2.8배이고, 3회 중 2회가 리뷰 후 수정까지 간다.
- 라우터 재측정(lean + xhigh→high, `runs/pilot-c2-router.jsonl`, 2026-10-04): L1~L4 12건 유효, L5는 리뷰 수정 단계에서 mer error(원인 미기록), 같은 파일로 다시 돌린 2차 13건은 모두 2.7초 만에 mer error. 2차가 1차 diff를 빈 diff로 덮어써 c2 품질은 판정 못 함(덮어쓰기와 오류 사유 미기록은 수정).
  - 리뷰 없는 9건: Sonnet 기준선 $2.14, Opus $3.79, 이전 라우터 $1.98, lean 라우터 $1.54(Sonnet 대비 −28%, Opus 대비 −59%).
  - Opus 리뷰가 붙은 3건: Sonnet $0.71, Opus $1.38, lean 라우터 $1.12(Sonnet 대비 +58%, Opus 대비 −19%).
  - 12건 합계: lean 라우터 $2.66, Sonnet 대비 −6%, Opus 대비 −48%.
  - 기준선은 플러그인을 모두 불러오는 stock 상태라, 절감의 상당 부분은 mer 세션의 lean 맥락에서 온다. advisory hook만 쓰는 사용자 세션에는 lean이 적용되지 않는다.
- 라우터 재측정 c3(`runs/pilot-c3-router.jsonl`, 2026-10-04): 13건 모두 정상 종료, 저장된 diff 13개를 다시 적용하면 모두 테스트 통과. pilot-l5는 이번에 Jev가 L3로 분류해 Sonnet high + Opus 리뷰(수정 요청 후 수정) $0.69.
  - 리뷰 없는 9건: lean 라우터 $1.55(Sonnet 기준선 대비 −28%, Opus 대비 −59%).
  - Opus 리뷰 3건: $1.05(Sonnet 대비 +48%, Opus 대비 −24%).
  - 13건 합계: $3.28, Sonnet 기준선($3.13) 대비 +5%, Opus 기준선($5.72) 대비 −43%.
  - Phase 5 완료 조건(같은 흐름으로 동작, 파일럿 품질 유지)은 이 측정으로 충족했다.
- 결론: 기본 모델이 Sonnet인 사용자에게 라우터는 비용 절감 수단이 아니다. 비용 이득은 기본 모델이 Opus일 때만 있다.

### Phase 6 — 추가 Backend

- Jev Backend (§8.2 정의 완료 후)
- Nimble Backend (선택)
- Backend 비교와 confidence 보정

완료 조건: Backend를 교체해도 Stage Policy가 바뀌지 않으며, Backend별 품질·비용 차이를 같은 Corpus로 비교할 수 있다.

### Phase 7 — 요청 단위 라우팅 전환 (3차 개정)

1. **spike (live, 사용자 승인 필요)**: 같은 세션을 다른 모델·effort로 이어서 실행하는 방법 확인. `codex exec resume <id> -m ... -c model_reasoning_effort=...`가 대화 컨텍스트를 유지하는지, 캐시가 끊기는지, 비용이 얼마인지. 안 되면 app-server 턴 단위 변경을 확인한다.
2. **측정 도구 보완**: 실행 기록에 판정 레벨·세션 프로필·승격 횟수를 남기고, 실행 후 diff를 보존해 요구사항 충족을 사람이 판정할 수 있게 한다.
3. **구현**: `mer` CLI(판정, 세션 실행, Test Gate, 승격, 고위험 독립 Review, 로그), Policy의 세션 프로필·승격 사다리(§11.4), 플러그인 hook을 조언 모드로 축소. 분류는 규칙 기반을 먼저 쓰고 애매할 때만 모델을 호출하는 방식을 검토한다.
4. **파일럿 재측정 (live, 승인 필요)**: 같은 4건, 같은 기준선(gpt-6-luna / high). 성공 기준: 테스트 통과·요구사항 충족을 유지하면서 전체 사용량이 기준선 이하.
5. **정리 (완료, 2026-10-01)**: 재측정을 통과해 단계별 subagent 오케스트레이션 코드(§3.8)를 삭제했고 hook은 조언 전용이 됐다(§3.7). 통과하지 못했다면 기본 모드를 `off`로 두고 고위험 작업 독립 Review 도구로 범위를 줄인다.

완료 조건: 파일럿 재측정 결과가 기록되고, 그 결과에 따라 기본 모드(`auto` 또는 `off`)가 결정된다.

---

## 25. MVP 완료 기준

MVP = Phase 0 ~ 4 (Codex).

- Codex용 Host Plugin으로 설치·실행할 수 있다.
- 일반 개발 작업 요청 시 사용자가 Router를 호출하지 않아도 자동으로 라우팅된다.
- 대화·단순 질문은 라우팅하지 않는다.
- Plan / Implement / Review 단계마다 단일 모델·effort가 결정되고 실제로 적용된다.
- 요청 effort와 실제 적용 effort가 로그에 남는다.
- 위험 신호가 있으면 최소 프로필이 적용된다.
- Review가 Implement와 별도 실행·별도 컨텍스트로 수행된다.
- Test / Lint / Type Check를 deterministic gate로 실행하고, 실행하지 못한 검사는 `not_run`으로 보고한다.
- 작업 범위가 크게 바뀔 때만 재라우팅한다.
- 플러그인 내부에서 호스트 구독 모델만 사용한다.
- Backend를 설정으로 선택할 수 있고, 출력이 `DifficultyDecision`으로 정규화된다.
- 고정 모델 Baseline 대비 품질과 전체 사용량을 비교한 결과가 있다.

MVP 이후: Claude Code Plugin, Jev·Nimble Backend 비교.

현재 충족 상태:

| 기준 | 상태 |
|---|---|
| 설치·실행, 자동 라우팅, 단계별 모델·effort 적용, 별도 컨텍스트 Review, Test Gate `not_run` 보고 | live 확인 (L2 작업 1건) |
| 요청·적용 effort 로그, 위험 신호 최소 프로필, Backend 설정 선택과 정규화 | 단위 테스트 확인 |
| 대화·단순 질문 비라우팅 | 단위 테스트만 (live 미확인) |
| 차단 경로(지침과 다른 subagent 생성) | 단위 테스트만 (live에서 발생하지 않음) |
| 재라우팅 | 미구현 (§3.5) |
| Baseline 대비 품질·사용량 비교 결과 | 2차 구조로 수행: 사용량 약 3.1배로 **불합격**. 3차 구조로 재측정 예정(Phase 7) |

3차 개정 이후 MVP 기준은 Phase 7 완료 조건을 따른다: `mer` CLI로 요청 단위 라우팅·Test Gate·승격·고위험 독립 Review가 동작하고, 파일럿에서 기준선 이하 사용량을 보인다.

---

## 26. 미결 사항

| 항목 | 상태 / 해소 시점 |
|---|---|
| 요청 단위 라우팅 + cascade가 기준선 대비 사용량을 줄이는가 | **최우선**. Phase 7 파일럿 재측정 (2차 구조는 약 3.1배로 불합격) |
| 해소됨: 같은 세션 모델 변경은 `exec resume -m`으로 동작, 모델 변경 턴은 캐시 대부분 끊김 | Phase 7 spike |
| 측정 도구: diff 보존, 판정 레벨 기록 | Phase 7 |
| Routing Corpus 라벨 담당자와 150건 라벨링 | 기준선 비교 결과가 긍정적이면 진행 |
| balanced tier 모델(현재 economy와 같은 gpt-6-luna) | 기준선 비교와 함께 결정 |
| hook timeout fail-open, 취소 후 중복 실행 재측정 | 증거 미보존. 다음 live 확인 때 |
| 50KB 이상 산출물 전달 | 미검증 |
| 메인 모델이 차단 사유를 따라 재시도하는가 | live 미관측 |
| 플러그인 업데이트 후 hook 재신뢰 필요 조건 | hook 설정이 같으면 유지됨. 설정 변경 시 미확인 |
| `updatedInput`·`tool_name` 형식의 버전 의존성 | 버전 업그레이드 시 재확인 |
| 해소됨: Jev의 정체(TypeSafe 외부 API), 실행 방식(HTTPS), 비용(별도 과금, §8.2). 실제 응답 품질은 live 비교 때 확인 | Phase 6 |
| Backend별 confidence 임계값 | Phase 6 |
| 해소됨: subagent 모델·effort 동적 지정, 구독 인증 분류 호출, Codex 모델별 지원 effort, rollout `token_count` 형식 | Phase 0 / live 테스트 |

---

## 27. 최종 정의

```text
사용자 요청 (mer CLI / TUI + 조언 hook)
 ↓
Router Core
 ├─ 라우팅 대상 판정
 ├─ Difficulty Backend (규칙 우선 → 분류 모델)
 ├─ DifficultyDecision (L1 ~ L5 + risk_flags)
 └─ Policy (세션 프로필, 승격 사다리, 독립 Review 여부)
 ↓
Host Adapter (tier/effort 매핑, 세션 실행·재개)
 ↓
구현 세션 하나 (계획 + 구현) → mer-gate → [실패 시 같은 세션 승격] → [고위험이면 독립 Review]
 ↓
Done + 라우팅 로그
```

설계 원칙:

1. **주 진입점은 `mer` CLI, 보조 진입점은 Host Plugin(조언)이며, Codex를 먼저 완성한다.**
2. **라우팅은 요청 단위다. 한 세션이 작업을 끝까지 처리하고, 실패할 때만 상위 설정으로 올린다.**
3. **난이도 판정기는 교체 가능한 Difficulty Backend이며, Stage Policy와 분리한다.**
4. **독립 Review는 고위험 작업에만, 별도 실행·별도 컨텍스트로 수행한다.**
5. **라우팅의 가치는 고정 모델 기준선 대비 측정으로 입증한다.**

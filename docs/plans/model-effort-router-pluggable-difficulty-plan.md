# Model-Effort Router Greenfield 기획서

> 개정: 2026-10-01 — 1차 검토 반영. 호스트 실행 모델을 "hook 개입"에서 "Router 주도 단계 실행"으로 변경, Stage Policy 단일값 확정, Effort Map·라우팅 대상 판정·Test Gate 탐색·평가 기준선 추가, Codex 우선 MVP로 범위 축소, 장 번호 정리.

## 1. 목적

Model-Effort Router는 개발 작업의 난이도를 판단하고, `Plan / Implement / Review` 각 단계에 사용할 모델과 reasoning effort를 결정한다.

핵심 목표:

- 제품은 **Codex Plugin / Claude Code Plugin 형태로 배포·실행**한다. **MVP는 Codex Plugin을 먼저 완성**하고, Claude Code Plugin은 그 다음 단계로 진행한다.
- 쉬운 작업에는 저비용 모델을 사용한다.
- 설계가 필요한 작업에는 상위 모델을 배정한다.
- 구현과 리뷰를 **별도 실행·별도 컨텍스트**로 분리한다.
- 리뷰는 구현보다 보수적인 모델·effort 정책을 적용한다.
- Codex, Claude Code 등 각 호스트의 구독형 실행 환경을 그대로 사용한다.
- 난이도 판단기는 특정 제품에 종속하지 않고 교체 가능하게 만든다.
- 고정 모델로 실행하는 것보다 **전체 사용량이 실제로 줄어드는지** 측정으로 입증한다.

핵심 원칙:

> **Difficulty Backend가 난이도를 판단하고, Router가 난이도에 따라 Plan·Implement·Review의 순서와 모델·effort를 결정하며, 실제 실행은 호스트의 subagent가 담당한다.**

---

## 2. 제품 형태: Host Plugin 기반

Model-Effort Router는 독립 LLM 서비스가 아니라 **호스트 에이전트에 설치되는 플러그인**이다.

대상 호스트:

```text
Codex Plugin        (MVP)
Claude Code Plugin  (MVP 이후)
```

각 플러그인은 공통 `Router Core`를 포함하거나 참조하고, 호스트별 차이는 Adapter에서만 처리한다.

```text
Codex / Claude Code
  ↓
Host Plugin
  ├─ Host Hook Adapter   (요청 감지 → Router 진입)
  ├─ Router Core
  │   ├─ Difficulty Backend
  │   └─ Stage Policy
  └─ Host Adapter        (프로필 → 호스트 모델·effort → subagent 실행)
  ↓
Host Runtime / Subscription
```

### 2.1 플러그인의 역할

- 호스트의 요청 이벤트에 진입점 등록
- 라우팅 대상 작업이면 Router Core로 전달
- Difficulty Backend 실행
- Stage Policy 결과로 단계별 실행 프로필 생성
- 단계별 subagent를 지정 프로필로 실행
- 단계 간 컨텍스트(Plan 결과, diff, Test 결과) 전달
- Test Gate 실행
- Review 결과 전달

### 2.2 Router Core의 역할

```text
Router Core
├─ Difficulty Backend Contract
├─ DifficultyDecision
├─ L1 ~ L5 정의
├─ Stage Policy
└─ Abstract Profile (model tier + effort)
```

Codex와 Claude Code는 같은 Core를 사용하고, 실제 모델·effort 매핑과 실행 방식만 다르다.

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

## 3. 실행 모델: Hook 진입 + Router 주도 단계 실행

Plan / Implement / Review는 호스트가 아는 개념이 아니다. 호스트 hook은 일반적으로 컨텍스트를 주입하거나 동작을 차단·검사할 수 있을 뿐, 임의 시점에 세션 모델을 바꾸는 것을 보장하지 않는다.

따라서 Router는 호스트 단계에 "끼어드는" 방식이 아니라, **단계를 직접 순서대로 실행하는 오케스트레이터**로 동작한다.

### 3.1 역할 분리

```text
Host Hook       : 요청 감지, 라우팅 대상 판정 트리거, 라우팅 지침 전달
Router          : 난이도 판정 요청, 단계 순서와 단계별 실행 프로필 결정
Host Adapter    : 지정 프로필로 단계별 subagent 실행, 결과 수집
```

Hook은 난이도를 판단하지 않는다. Router는 호스트 이벤트 API를 알지 않는다.

### 3.2 호스트 기능 전제 (Phase 0 spike로 검증)

문서상 확인된 전제와 검증이 필요한 항목을 구분한다.

| 항목 | Codex | Claude Code | 상태 |
|---|---|---|---|
| 사용자 요청 시점 hook (`UserPromptSubmit` 등) | 문서상 있음 | 문서상 있음 | 플러그인에서 실제 동작 검증 필요 |
| subagent별 `model` 지정 | 문서상 있음 | 문서상 있음 | 검증 필요 |
| subagent별 effort 지정 | 문서상 있음 (`model_reasoning_effort`) | 문서상 있음 (`effort`, 모델별 지원 상이) | 검증 필요 |
| subagent 호출 가로채기·검증 hook | 문서상 있음 | 확인 필요 | 검증 필요 |
| 모델·effort를 **실행 시점에 동적으로** 넘길 수 있는지 | 미확인 | 미확인 | **핵심 미결** |

모델 전환 관련 hook(예: Claude Code의 모델 전환 전후 hook)은 이미 요청된 전환을 검사하거나 컨텍스트를 추가하는 기능이며, Router의 단계별 전환 수단으로 간주하지 않는다.

**동적 지정이 불가능한 경우**: subagent 정의가 정적 파일(frontmatter / TOML)이라면, 플러그인이 `stage × profile × effort` 조합별 subagent 정의를 미리 포함하고 Router는 그중 하나를 선택한다.

```text
mer-plan-frontier-high
mer-implement-balanced-high
mer-review-frontier-xhigh
...
```

조합 수를 줄이기 위해 Stage Policy가 실제로 출력하는 조합만 생성한다(§11 표 기준).

### 3.3 라우팅 대상 판정

모든 사용자 입력을 분류기에 보내지 않는다. 먼저 저비용 규칙으로 대상 여부를 판정한다.

| 입력 유형 | 처리 |
|---|---|
| 대화, 단순 설명, 상태 질문, 코드 읽기만 필요한 질문 | 라우팅하지 않음. 호스트 기본 동작 |
| 코드 변경이 필요한 개발 작업 | 전체 라우팅 (난이도 판정 → 필요한 단계 실행) |
| 리뷰만 요청 | Review 단계만 실행. 난이도 판정은 Review 프로필 결정용으로만 사용 |
| 계획만 요청 | Plan 단계만 실행 |

판정 규칙은 Router Core에 두고, 판정이 모호하면 라우팅하지 않는 쪽을 기본으로 한다(불필요한 분류 비용 방지).

### 3.4 Router 내부 단계 이벤트

`before_plan` 등은 **Router 내부 이벤트**이며 호스트 hook 이름이 아니다.

```text
on_task_start      난이도 판정 + RoutePlan 생성 (1회)
before_plan        Plan subagent 프로필 확정
before_implement   Implement subagent 프로필 확정
before_test_gate   검사 명령 확정
before_review      Review subagent 프로필 확정
on_task_end        라우팅 로그 기록
```

한 작업에 대해 난이도는 `on_task_start`에서 한 번만 판정한다.

```text
on_task_start
 ↓
RoutePlan
 ├─ stages: [plan, implement, test_gate, review]  (라우팅 대상 판정에 따라 일부 생략)
 ├─ plan profile
 ├─ implement profile
 └─ review profile
```

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

### 3.6 Router 모드와 Override

모드: `auto`(기본) / `manual` / `off`.

설정 위치와 우선순위(높은 것이 이김):

1. 현재 요청에서 **사용자가 직접 입력한** 작업별 override (예: 메시지 첫 줄의 `/router off`, `/router implement=frontier:high`)
2. 저장소 설정 파일 (`.model-effort-router.yaml`)
3. 사용자 전역 설정
4. 내장 기본값 (`mode: auto`)

```yaml
# .model-effort-router.yaml
router:
  mode: auto
difficulty:
  backend: subscription
  fallback: none
```

안전 규칙: 인용문, 붙여넣은 텍스트, 저장소 파일 내용, 도구 출력 안에 나온 `router: off` 같은 문자열은 사용자 명령으로 해석하지 않는다. Override는 사용자가 직접 입력한 명령 형식에서만 인식한다.

### 3.7 Host Hook Adapter

```text
Host Event → Host Hook Adapter → Router Core
```

```text
HostHookAdapter
 ├─ CodexHookAdapter
 └─ ClaudeCodeHookAdapter
```

호스트 이벤트 구조가 바뀌어도 Router Core는 수정하지 않는다.

---

## 4. 전체 구조

```text
사용자 요청
   ↓
Host Hook → 라우팅 대상 판정
   ↓
Difficulty Backend
 ├─ Subscription LLM (MVP 후보)
 ├─ Jev
 └─ Nimble
   ↓
DifficultyDecision (L1 ~ L5 + risk_flags)
   ↓
Stage Policy (단계별 단일 profile + effort)
   ↓
Host Adapter (호스트 모델·effort 매핑, subagent 실행)
   ↓
Plan → Implement → Deterministic Test Gate → Review
   ↓
완료 + 라우팅 로그
```

Backend를 교체해도 Stage Policy, Host Adapter, 단계 실행, Test Gate, Review는 변경되지 않는다.

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

### 8.1 Subscription LLM Backend (MVP 후보)

호스트 구독 안의 저가 모델(economy tier)에 L1~L5 분류 프롬프트를 실행한다. 추가 설치가 없어 MVP 기본값으로 가장 현실적이다.

전제 검증(Phase 0):

- 플러그인 컨텍스트에서 구독 인증만으로 분류 호출이 가능한가
- 분류 호출 지연이 hook timeout 안에 들어오는가
- 분류 호출 사용량이 절감 효과를 상쇄하지 않는가(§22.3)

### 8.2 Jev Backend

Jev 고유의 입력 스키마, typed decision, 내부 판단 방법은 `JevBackend` 안에 격리한다.

도입 전 정의할 것(현재 미정):

- 제품/저장소 위치와 라이선스
- 실행 방식(로컬 프로세스 / 호스트 모델 호출 / 외부 서비스)
- 호출당 지연과 비용

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

```yaml
difficulty:
  backend: subscription   # subscription | jev | nimble | custom
  fallback: none          # 다른 backend 이름 또는 none
  timeout_s: 10
```

Registry:

```python
BACKENDS = {
    "subscription": SubscriptionBackend,
    "jev": JevBackend,
    "nimble": NimbleBackend,
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

### 11.1 레벨별 기본값

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

최소 조건은 기본값보다 낮출 때 쓰지 않는다. 기본값이 이미 높으면 기본값을 유지한다.

**불확실성 승격** (Backend별 검증 후 활성화):

- `confidence`가 Backend별 임계값보다 낮으면 level을 한 단계 올려 정책을 적용한다.
- 임계값은 Backend마다 Routing Corpus로 보정한다. 보정 전에는 비활성 상태로 둔다.
- 공통 임계값은 사용하지 않는다.

### 11.3 출력

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

---

## 12. Host Model Map / Effort Map

Router는 실제 모델 이름 대신 추상 tier와 추상 effort를 사용한다.

```text
tier   : economy | balanced | frontier
effort : medium | high | xhigh
```

Host Adapter가 두 가지를 모두 매핑한다.

```yaml
# 예: codex adapter 설정 (모델명은 설치 시점의 호스트 모델로 채움)
tiers:
  economy:  <현재 저비용 모델>
  balanced: <현재 주력 구현 모델>
  frontier: <현재 최고 reasoning 모델>
efforts:
  medium: medium
  high:   high
  xhigh:  xhigh
```

```yaml
# 예: claude code adapter 설정
tiers:
  economy:  <현재 Haiku 계열>
  balanced: <현재 Sonnet 계열>
  frontier: <현재 Opus 계열>
efforts:
  medium: medium
  high:   high
  xhigh:  xhigh
```

**모델별 지원 effort 처리**

- Adapter는 모델별 지원 effort 목록을 가진다.
- 요청 effort를 선택한 모델이 지원하지 않으면 지원되는 값 중 **가장 가까운 상위값**, 상위값이 없으면 **최대 지원값**을 적용한다.
- 요청값과 실제 적용값을 모두 라우팅 로그에 기록한다.

모델 버전이 바뀌어도 Difficulty Backend와 Stage Policy는 수정하지 않는다. Adapter 설정만 갱신한다.

---

## 13. Plan 단계

Plan은 다음을 정리한다.

- 요구사항 해석
- 변경 대상
- 접근 방법
- 예상 변경 범위
- 구현 순서
- 테스트 방법
- 주요 위험 요소

L1·L2는 기본 생략하고, L3 이상 또는 위험 신호가 있으면 수행한다. Plan 결과가 최초 분류보다 복잡도를 크게 드러내면 재라우팅(§3.5)한다.

---

## 14. Implement 단계

Implement는 Plan을 실제 코드 변경으로 바꾼다. 구현 모델은 항상 최고 모델일 필요가 없다.

```text
Plan       → 판단력 우선
Implement  → 비용 대비 구현력 우선
Review     → 검증 능력 우선
```

이 차등 배정이 주요 비용 절감 지점이다.

---

## 15. Deterministic Test Gate

Implement와 Review 사이에 deterministic gate를 둔다. Test는 별도 LLM 역할로 정의하지 않는다.

검사 종류: unit test, lint, type check, build, 정적 검증.

**검사 명령 탐색 순서**

1. Router 설정 파일의 명시 명령
2. 저장소 지침 문서(`AGENTS.md`, `CLAUDE.md` 등)와 CI 설정
3. manifest scripts (`package.json`, `pyproject.toml`, `Makefile` 등)

**결과 상태**: `passed` / `failed` / `not_run`

- 찾지 못한 검사는 `not_run`으로 기록하며 통과로 취급하지 않는다.
- 결과 전체(`not_run` 포함)를 Review 컨텍스트에 포함한다.

---

## 16. Review 단계

Review는 구현 결과를 독립적으로 검증한다.

확인 항목: 사용자 요구사항 충족, 구현 누락, 논리 오류, 회귀 가능성, 엣지 케이스, 설계 위반, 보안 문제, 과도한 변경, 테스트 누락.

**독립성 원칙**: Review는 Implement와 **별도 실행, 별도 컨텍스트**로 수행한다. Implement의 대화 기록을 이어받지 않고, §17의 전달 항목만 입력으로 받는다. 프로필(모델·effort)은 같아도 된다(예: L1, L4).

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

각 단계는 이전 단계의 대화 전체가 아니라 정해진 산출물만 받는다.

| 단계 | 입력 |
|---|---|
| Plan | 사용자 요청, 저장소 컨텍스트 |
| Implement | 사용자 요청, Plan 결과(있을 때) |
| Test Gate | 작업 트리 |
| Review | 사용자 요청, Plan 결과, 변경 diff, Test Gate 결과 |
| Fix | Review 또는 Test 실패 내용, 변경 diff |

전달 산출물의 크기 상한을 두고, 초과 시 요약이 아니라 경로·범위 참조로 넘긴다.

---

## 18. 실행 예시

**L1**

```text
Plan 생략 → Implement: economy/medium → Test Gate → Review: economy/medium (별도 컨텍스트) → Done
```

**L3**

```text
Plan: frontier/high → Implement: balanced/high → Test Gate → Review: frontier/high → Done
```

**L2 + risk_flags=[auth]**

```text
Plan: frontier/high (위험 신호로 수행) → Implement: economy/medium → Test Gate → Review: frontier/high → Done
```

**L5**

```text
Plan: frontier/xhigh → Implement: frontier/high → Test Gate → Review: frontier/xhigh → Done
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

로그는 예측과 실행 결과를 제공할 뿐 **정답 라벨이 아니다**. Routing Corpus 후보 수집에 사용하되, 라벨은 §22.1 절차로 붙인다.

---

## 22. 평가

### 22.1 Routing Corpus

- **라벨 기준**: §10 Level 정의와 레벨별 예시 작업 목록(앵커)을 문서로 고정한다.
- **라벨 담당**: 최소 2명이 독립 라벨링한다.
- **불일치 처리**: 1단계 차이는 논의 후 합의, 2단계 이상 차이는 기준 문서를 보완한 뒤 재라벨링한다.
- **표본 구성**: L1~L5 각 레벨과 위험 신호 작업을 모두 포함한다. 초기 목표 150건 이상.
- 라우팅 로그는 후보 수집원으로만 쓴다.

### 22.2 Backend 비교

같은 Corpus에서 Backend를 직접 비교한다. 이름이나 공개 benchmark만 보고 기본값을 바꾸지 않는다.

- Exact Level Accuracy
- ±1 Level Accuracy
- Over-routing / Under-routing
- Critical task miss (L4·L5 또는 위험 신호 작업을 L2 이하로 판정)
- latency, token usage, cost, local resource usage
- confidence 보정 결과(§11.2 임계값 산출용)

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

배포 구조:

```text
packages/
├── router-core/
├── codex-model-effort-router/
│   ├── plugin metadata
│   ├── hooks/            (Host Hook Adapter 진입점)
│   ├── agents/           (stage×profile×effort subagent 정의, 필요 시)
│   ├── adapter config    (tier/effort map)
│   └── router-core bundle/reference
└── claude-model-effort-router/   (MVP 이후)
    └── (동일 구성)
```

Core 구조:

```text
model_effort_router/
├── difficulty/
│   ├── base.py
│   ├── decision.py
│   ├── registry.py
│   ├── risk.py            (규칙 기반 risk_flags 탐지)
│   └── subscription.py
├── policy/
│   ├── levels.py
│   ├── targeting.py       (라우팅 대상 판정)
│   ├── stages.py
│   └── router.py
├── profiles/
│   └── profiles.py        (tier, effort)
├── adapters/
│   └── codex.py
├── gate/
│   └── discovery.py       (Test Gate 명령 탐색)
├── logging/
│   └── route_log.py
├── evaluation/
│   ├── routing_corpus.py
│   ├── compare_backends.py
│   └── baseline.py
└── tests/
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

### Phase 5 — Claude Code Plugin

- Claude Code Hook Adapter, Host Adapter, subagent 정의

완료 조건: 같은 Router Core로 Claude Code에서 Phase 3과 같은 흐름이 동작한다.

### Phase 6 — 추가 Backend

- Jev Backend (§8.2 정의 완료 후)
- Nimble Backend (선택)
- Backend 비교와 confidence 보정

완료 조건: Backend를 교체해도 Stage Policy가 바뀌지 않으며, Backend별 품질·비용 차이를 같은 Corpus로 비교할 수 있다.

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

---

## 26. 미결 사항

| 항목 | 해소 시점 |
|---|---|
| subagent 모델·effort 동적 지정 가능 여부 | Phase 0 |
| 구독 인증으로 분류 호출 가능 여부와 지연 | Phase 0 |
| 호스트별 실제 tier 모델명과 모델별 지원 effort | Phase 0 / Phase 2 |
| Jev의 정체, 실행 방식, 비용 | Phase 6 이전 |
| Routing Corpus 라벨 담당자 | Phase 4 이전 |
| Backend별 confidence 임계값 | Phase 6 |

---

## 27. 최종 정의

```text
Codex / Claude Code
 ↓
Host Plugin
 ↓
Host Hook Adapter → 라우팅 대상 판정
 ↓
Router Core
 ├─ Difficulty Backend (Subscription / Jev / Nimble / Future)
 ├─ DifficultyDecision (L1 ~ L5 + risk_flags)
 └─ Stage Policy (단계별 단일 tier + effort)
 ↓
Host Adapter (tier/effort 매핑, subagent 실행)
 ↓
Plan → Implement → Test Gate → Review (별도 컨텍스트)
 ↓
Done + 라우팅 로그
```

설계 원칙:

1. **Model-Effort Router는 Codex/Claude Code에 설치되는 Host Plugin으로 제공하며, Codex를 먼저 완성한다.**
2. **Hook은 진입만 담당하고, 단계 순서와 실행은 Router가 subagent로 주도한다.**
3. **난이도 판정기는 교체 가능한 Difficulty Backend이며, Stage Policy와 분리한다.**
4. **Review는 별도 실행·별도 컨텍스트로 수행한다.**
5. **라우팅의 가치는 고정 모델 기준선 대비 측정으로 입증한다.**

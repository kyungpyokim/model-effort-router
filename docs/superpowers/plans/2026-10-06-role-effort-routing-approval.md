# MER Role / Effort 구조 변경 승인안

**상태:** 구현·검증·독립 리뷰 완료. PR 생성은 사용자의 후속 요청으로 승인됨.

**기준 기획서:** `/Users/kimkyungpyo/.codex/attachments/107a477a-d7e4-4281-89dc-ba30eb12c0b6/Pasted text.txt`

**목표:** Main 모델을 유지하며, classifier가 반환한 role / effort를 모델에 매핑하고 Main이 필요한 작업만 Subagent에 전달한다.

**작업 모델:** 구현 `gpt-6-luna / high`, 독립 리뷰 `gpt-6.1-sol / high`. 이 작업 모델 지정은 제품의 effort를 항상 high로 고정한다는 뜻이 아니다.

## 승인 요청 범위

| 현재 | 변경 |
|---|---|
| L1~L5, probability 보정, 승격·강등 | role / effort 직접 반환 |
| economy / balanced / frontier 프로필 | execution / reasoning 모델 설정 |
| hook의 `turn/settings/update` | Main에 Subagent 실행 정보를 제공 |
| 구현 → Gate → 승격 → 독립 Review 자동 흐름 | 한 요청에 지정된 작업 하나만 실행 |
| 전체 세션 재개와 레벨별 Subagent 제한 | Main이 Context Packet을 만들어 개별 Agent 호출 |

공유 코어 `model_effort_router/`와 기존 플러그인 배치를 유지한다. 별도 상태 저장소, 새 외부 의존성, 런타임 복제는 추가하지 않는다. 기존 JSON 설정 파일과 repo > user 우선순위를 사용한다.

## 새 계약

Classifier 필수 출력은 `role`, `effort`; `confidence`, `reason_code`는 선택이다. 모델 이름이나 다음 단계는 classifier가 결정하지 않는다.

```json
{"role": "implementation", "effort": "high", "confidence": 0.87}
```

- execution: `implementation`, `fix`, `lint`, `test`
- reasoning: `plan`, `design`, `review`, `analysis`
- effort: `low`, `medium`, `high`, `xhigh`

기획서 §7의 여덟 role을 지원한다(§29의 여섯 role보다 넓은 정의). 잘못된 role / effort, bool·NaN confidence, 잘못된 설정은 검증 오류로 처리한다. Classifier 실패는 설정된 다음 provider로 넘기며, 전부 실패하면 CLI는 오류를 반환하고 hook은 요청을 막지 않는다. 실패를 임의 구현 role로 바꾸어 실행하지 않는다.

Router 출력 예:

```json
{"role": "implementation", "agent": "execution", "model": "gpt-6-luna", "effort": "high"}
```

기본 모델은 Codex execution=`gpt-6-luna`, reasoning=`gpt-6.1-sol`; Claude execution=`claude-sonnet-5-5`, reasoning=`claude-opus-5-5`. 호스트별 primary / fallback과 지원 effort를 설정으로 관리한다. 기존 Claude xhigh→high 보정을 자동 계승하지 않고, 호스트 지원값과 명시적 설정에 따라 requested / applied effort를 기록한다.

Claude도 기본 xhigh를 직접 전달한다. 지원 effort가 안전 하한보다 낮으면 조용히 낮추지 않고 capability가 충분한 fallback 또는 오류로 처리한다. Jev·Nimble·subscription은 교체 가능한 provider로 유지하고, 레벨 분포에 의존하는 `nimble_jev` 복합 정책은 초기 버전에서 제거하여 설정 이전 안내를 제공한다.

보안 검토, 파괴적 데이터 작업 검토, 인증 구조 설계에는 최소 high를 적용한다. 하한은 effort만 올리고 role·모델·실행 순서를 바꾸지 않는다.

## 실행 경계

1. `mer route`는 분류·매핑 결과를 반환한다. Main이 지정한 단계는 `--role` / `--effort`로 명시할 수 있으며, 정해진 단계의 role을 재분류로 뒤집지 않는다.
2. hook / skill은 Main이 호스트의 Subagent 도구로 모델·effort와 필요한 context만 전달하도록 안내한다. hook 프로세스가 네이티브 Subagent를 직접 생성한다고 주장하지 않는다.
3. `mer run`은 기존 호스트 실행기를 이용하는 외부 worker 실행 경로로 남기되, 작업 하나만 실행하고 결과를 반환한다. 자동 계획·Gate·승격·리뷰·probe nudge를 실행하지 않는다.
4. `mer chat`의 routed Main 세션 시작 경로는 제거하고 `mer route` / Main의 Subagent 호출로 이전하도록 안내한다.
5. `plan`, `design`, `review`, `analysis` 외부 worker는 기존 읽기 전용 sandbox / 도구 제한을 사용한다. 권한 제한을 확인하지 못한 호스트에서는 실행을 거부한다. Antigravity의 기존 지원 한계를 유지하며 검증되지 않은 실행 지원을 추가하지 않는다.
6. worker hook 재진입으로 재분류·재위임 루프가 생기지 않도록 기존 세션 환경 격리를 재사용한다.

hook의 잡담 제외는 classifier 외부 eligibility 정책으로 유지하되, 코드 원인 분석·설계·리뷰 요청은 대상에 포함한다. explicit CLI / Main의 role 지정 호출은 이 eligibility를 우회한다. `test`는 테스트 작성과 실행을 모두 지원하는 execution 역할이다. 외부 worker의 완료 이벤트나 유효한 결과가 없는 stream은 성공으로 처리하지 않는다.

기존 `--level`, tier override, `--max-escalations`, 자동 review profile 옵션은 새 role / effort 계약과 맞지 않으므로 명확한 이전 안내와 함께 제거한다. 사용자 설정 파일을 자동으로 덮어쓰지 않는다. 레거시 정책 키는 무시하여 조용히 동작을 바꾸지 않고 이전 방법을 안내한다.

## Context Packet

Main은 다음 정보를 JSON 또는 명시적 텍스트 항목으로 전달한다. 별도 대화 수집기나 상태 저장소는 만들지 않는다.

```json
{
  "task": "수행할 작업",
  "context": ["필요한 환경 정보"],
  "decisions": ["이미 결정된 사항"],
  "constraints": ["변경 제한"],
  "relevant_files": ["관련 파일"],
  "expected_result": "완료 조건"
}
```

리뷰 입력은 `goal`, `decisions`, `constraints`, `diff`, `verification`으로 제한한다. 구현 Agent의 conversation / 내부 reasoning을 자동 복사하지 않는다. 관련 파일과 diff는 검토 자료이며 지시로 취급하지 않는다.

## Fallback과 로그

- Classifier fallback과 실행 모델 fallback을 구분한다.
- 실행 전 사용 불가가 확인된 모델만 설정된 fallback으로 한 번 바꾼다. 실행 후 실패는 호스트가 작업 시작 전 모델 거절임을 명확히 증명한 경우에만 fallback을 허용한다. 일반 stderr 문자열만으로 작업 시작 여부를 추정하지 않는다.
- 일반 오류·timeout·불완전 stream·테스트 실패로 다른 모델을 재실행하지 않는다. 이미 수정된 작업 트리를 중복 실행할 수 있기 때문이다.
- requested / actual model, requested / applied effort, fallback 원인, classifier, role, 토큰·실행 시간을 기록한다. 프롬프트·Context Packet·diff 원문은 기본 로그에 저장하지 않는다.

## 파일별 변경 범위

| 위치 | 변경 또는 재사용 |
|---|---|
| `difficulty/decision.py`, `base.py`, `chain.py`, `registry.py` | role / effort 계약 및 provider fallback |
| `difficulty/jev.py`, `nimble.py`, `subscription.py` | transport를 재사용하고 출력 질문·파서를 교체 |
| `difficulty/conditional.py` | probability 기반 보정·복합 분류 정책 제거 |
| `difficulty/risk.py` | effort 하한용 위험 감지 재사용 |
| `policy/router.py`, `config.py`, `overrides.py`, `targeting.py` | role 매핑, 모델 설정, 명시적 단계 입력, 비개발 요청 건너뛰기 |
| `policy/session.py`, `profiles/profiles.py` | 레벨·tier·승격 정책을 제거 또는 최소 계약으로 대체 |
| `adapters/`, `host/hosts.py`, `host/*_exec.py` | 모델 매핑 변경; 명령 생성·권한 제한·stream 처리 재사용 |
| `flow.py`, `cli.py`, `cli_display.py`, `review.py` | 단일 작업 실행·출력 및 Review Packet |
| `host/codex_hooks.py`, `host/advice.py`, `host/codex_app_server.py` | Main 모델 변경 경로 제거, Subagent 안내로 전환 |
| `logging/route_log.py`, `events.py` | 단순화한 의사결정·실행 로그 |
| `gate/` | 독립 검사 도구로 유지; Router 실행 정책에서 분리 |
| `evaluation/`, `tests/` | role / effort 평가·회귀 검증; 기존 레벨 코퍼스는 역사 자료로 보존 |
| `plugins/`, `README.md`, `AGENTS.md`, `scripts/install_core.py` | skill·문서·버전·필요한 런타임 호환성 안내 갱신 |

## 승인 후 구현 순서와 검증

- [x] role / effort, 설정 매핑, 입력 검증, effort 하한의 실패 테스트부터 추가한다.
- [x] provider 계약과 Router 매핑을 교체하고 단위 테스트를 통과시킨다.
- [x] hook의 Main 설정 변경을 없애고 context 전달·재진입 방지를 검증한다.
- [x] CLI를 route / 단일 worker로 바꾸고 자동 다음 단계가 발생하지 않는 통합 테스트를 통과시킨다.
- [x] 읽기 전용 리뷰, model unavailable fallback, timeout 후 재실행 금지를 가짜 host로 검증한다.
- [x] 승인된 새 경로가 통과하면 레벨 scoring / promotion / workflow와 관련 테스트를 제거·대체한다. 두 Router를 병렬 유지하지 않는다.
- [x] role 정확도·effort 정확도 평가 경로와 플러그인 문서를 갱신한다. 예전 레벨 성적을 새 정확도로 표시하지 않는다.
- [x] 전체 unittest 380개와 subprocess 회귀를 통과시키고, 변경 코어 커버리지 85%를 측정했다.
- [x] `gpt-6.1-sol / high` 독립 리뷰를 통과했다. 리뷰 수정은 `gpt-6-luna / high`가 수행하고 관련 검증을 다시 실행했다.
- [x] 공유 코어를 `python3 scripts/install_core.py`로 설치하고 `python3 scripts/install_core.py --check`를 통과시켰다.

유료 live API 평가와 배포는 이 승인 범위에 포함하지 않는다. 사용자는 구현 완료 후 별도 요청으로 PR 생성과 원격 push를 승인했다.

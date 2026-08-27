# SIP 검증 추천 설계

**목표:** 검사를 실행하거나 분류기를 한 번 더 호출하지 않고, 라우팅된 에이전트가 고려할 저장소 독립적 검사를 모든 route JSON에 표시한다.

## 범위

이는 Paperthin에서 영감을 얻은 SIP의 첫 번째 증분이다. `scripts/router.py`가
생성하는 모든 route JSON에 추가 전용 `verification` 객체를 포함한다. 명령 실행,
대상 저장소 검사, 실패한 실행자의 재시도, 모델·추론 수준 선택 변경, route-file
명령 체인 변경은 포함하지 않는다.

## 호환성

- `schema_version`은 `1`로 유지한다. 새 객체는 추가 전용이며 route-file 재생은
  계속 `platform`, `mode`, `steps`만 검증하고 실행한다.
- `RouteResult`는 변경하지 않는다. `result_payload()`가 이미 선택된 라우트를
  직렬화할 때 추천을 계산한다.
- 설정이나 의존성을 추가하지 않는다. 검사는 저장소별 명령이 아니라 안정적인
  Router 정책이다.
- 루트 `scripts/router.py`와 `references/routing-policy.md`를 변경한 뒤,
  `scripts/sync_bundle.py`로 세 공유 산출물을 동기화한다.

## JSON 계약

새로 생성하는 모든 JSON payload에는 다음이 포함된다.

```json
{
  "verification": {
    "recommended": [
      {"id": "focused_tests", "reason": "Code changes need focused regression coverage."}
    ],
    "skipped": [
      {"id": "security_review", "reason": "No security, authentication, authorization, or payment risk is active."}
    ]
  }
}
```

`id`는 안정적인 기계 판독용 식별자다. `reason`은 간결한 사람이 읽는 설명이다.
두 필드 모두 셸 명령이나 경로가 아니며, 검사가 실행됐다는 주장을 하지 않는다.
목록은 결정적이며 중복 ID를 포함하지 않는다.

## 선택 규칙

Router는 아래 검사를 정확히 이 순서로 평가한다.

1. `focused_tests` — `implementation`, `local_refactoring`,
   `architectural_refactoring`에 추천한다. 그 외에는 코드 변경을 요청한
   라우트가 아니므로 제외한다.
2. `plan_validation` — 두 단계 라우트에 추천한다. 그 외에는 검증할 계획
   산출물이 없으므로 제외한다.
3. `contract_review` — `design`, `review`, 또는 활성화된
   `public_api_change` 플래그에 추천한다. 그 외에는 외부 계약이 표시되지
   않았으므로 제외한다.
4. `security_review` — `security_sensitive`, `authentication`,
   `authorization`, `payment` 중 하나가 활성화됐을 때 추천한다. 그 외에는
   제외한다.
5. `migration_safety` — `data_migration`이 활성화됐을 때 추천한다. 그 외에는
   제외한다.
6. `broad_regression` — 유효 수준이 `L4` 또는 `L5`일 때 추천한다. 그 외에는
   라우팅 범위가 제한적이므로 제외한다.

이후 에이전트나 운영자가 추천 ID에 맞는 저장소별 명령을 선택한다. 제외된 ID는
추천하지 않은 사유를 알릴 뿐, 사람이 해당 검사를 실행하는 것을 금지하지 않는다.

## 구현 경계

`scripts/router.py`에 `task_type`, 유효 `level`, `risk_flags`, `mode`를 받아
`verification` 객체를 반환하는 순수 헬퍼 하나를 추가한다. `result_payload()`가
이를 호출한다. 다른 라우팅, launcher, route-file 재생 코드는 변경하지 않는다.

객체와 여섯 ID는 `references/routing-policy.md` 및 루트 README에 문서화한다.
README는 bundle 동기화 대상이 아니므로 JSON 출력을 설명하는 플러그인 README만
갱신한다. 플러그인 launcher 동작은 바꾸지 않는다.

## 테스트와 수용 기준

1. 코드 변경을 수행하는 두 단계 L3 라우트는 `focused_tests`와
   `plan_validation`을 추천하고, 보안·마이그레이션·광범위 회귀 검사는
   제외한다.
2. 인증, 데이터 마이그레이션, 공개 API 위험이 있는 L4 라우트는
   `security_review`, `migration_safety`, `contract_review`,
   `broad_regression`을 추천한다.
3. L2 설계 라우트는 `contract_review`만 추천하고 나머지 ID는 제외했다고
   표시한다.
4. 기존 route-file 재생 테스트로 새 `verification` 객체가 든 payload도
   재분류 없이 재생됨을 증명한다.
5. 전체 Router 테스트, bundle 검증, 동기화 사본 assertion, 공백 검사가
   통과한다.

## 이번 증분의 비목표

- 셸 명령 실행 또는 선택
- 두 번째 Paperthin/모델 크기 분류기
- 자동 재시도, 평가 루프, PR 게이트
- L4-L5 prism 방식의 다중 관점 계획

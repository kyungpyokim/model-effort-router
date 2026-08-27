# SIP 검증 추천 구현 계획

> **에이전트 작업자용:** 이 계획을 작업 단위로 구현할 때 `superpowers:executing-plans`를 사용한다. 각 단계는 체크박스로 추적한다.

**목표:** route JSON에 저장소 독립적인 검증 추천·제외 사유를 추가하되, 명령 실행이나 추가 분류는 하지 않는다.

**구조:** `scripts/router.py`의 순수 헬퍼가 이미 선택된 `task_type`, 유효 수준, 위험 플래그, 실행 모드에서 `verification` 객체를 만든다. `result_payload()`만 이 객체를 직렬화하며, 기존 route-file 재생은 해당 객체를 실행 입력으로 사용하지 않는다.

**기술:** Python 표준 라이브러리, `unittest`, JSON, 기존 bundle 동기화 스크립트.

**명세:** `docs/superpowers/specs/2026-08-27-sip-verification-recommendations-design.md`

## 전역 제약

- `schema_version`은 `1`로 유지한다.
- 검사 ID는 `focused_tests`, `plan_validation`, `contract_review`, `security_review`, `migration_safety`, `broad_regression`만 사용한다.
- `verification`은 검사 명령·경로·실행 결과를 포함하지 않는다.
- Router 분류 호출 횟수, 모델/추론 수준 매핑, launcher, route-file 명령 체인은 바꾸지 않는다.
- 루트 공유 파일만 수정하고 `python3 scripts/sync_bundle.py`로 플러그인 사본을 생성한다.

---

### Task 1: 검증 추천 JSON 계약을 테스트로 고정

**파일:**
- 수정: `tests/test_router.py`

**인터페이스:** `router.result_payload(result, commands)`는 `recommended`와 `skipped` 배열을 가진 `verification` 객체를 반환한다. 각 항목은 문자열 `id`, 문자열 `reason`만 가진다.

- [ ] **Step 1: 두 단계 코드 변경 라우트의 기대값을 작성한다.** `CommandAndLauncherTests`에 `architectural_refactoring/L3` payload가 `focused_tests`, `plan_validation`을 추천하고 `security_review`, `migration_safety`, `broad_regression`을 제외하는 테스트를 추가한다.
- [ ] **Step 2: 실패를 확인한다.** `python3 -m unittest tests.test_router.CommandAndLauncherTests.test_two_stage_payload_recommends_code_and_plan_checks -v`를 실행한다. `verification` 키가 없어 실패해야 한다.
- [ ] **Step 3: 위험·계약·수준 조합의 기대값을 작성한다.** 인증, 데이터 마이그레이션, 공개 API 위험이 있는 L4 payload와 L2 `design` payload를 검증하는 별도 테스트를 추가한다.
- [ ] **Step 4: 실패를 확인한다.** 새 테스트 두 개를 실행해 `verification` 누락으로 실패함을 확인한다.

### Task 2: 순수 추천 헬퍼와 payload 연결 구현

**파일:**
- 수정: `scripts/router.py`
- 테스트: `tests/test_router.py`

**인터페이스:** `verification_recommendations(task_type: str, level: str, risk_flags: dict[str, bool], mode: str) -> dict[str, list[dict[str, str]]]`가 고정된 ID 순서로 추천·제외 목록을 반환한다. `result_payload()`는 반환값을 `verification` 키에 저장한다.

- [ ] **Step 1: 최소 구현을 추가한다.** 여섯 검사 ID를 지정된 순서로 평가하는 순수 헬퍼를 추가하고, 각 ID를 정확히 한 번 `recommended` 또는 `skipped`에 넣는다.
- [ ] **Step 2: payload에 연결한다.** `result_payload()`가 위 헬퍼의 결과를 추가하도록 수정한다. `RouteResult`, `SCHEMA_VERSION`, `command_chain_from_payload()`는 수정하지 않는다.
- [ ] **Step 3: 집중 테스트를 통과시킨다.** Task 1의 세 테스트와 기존 route-file 재생 테스트를 실행한다.
- [ ] **Step 4: 전체 Router 테스트를 통과시킨다.** `python3 -m unittest discover -s tests -v`를 실행한다.

### Task 3: 정책과 사용자 문서 동기화

**파일:**
- 수정: `references/routing-policy.md`
- 수정: `README.md`
- 수정: `plugins/codex-model-effort-router/README.md`
- 수정: `plugins/codex-model-effort-router/skills/route/SKILL.md`
- 생성: `plugins/*/scripts/router.py`, `plugins/*/references/routing-policy.md`

**인터페이스:** 정책 문서는 여섯 ID·선택 규칙·비실행 성격을 설명한다. JSON을 재사용하는 Codex 문서는 `verification`을 실행 결과로 오해하지 않게 안내한다.

- [ ] **Step 1: 루트 정책을 갱신한다.** `verification` 객체와 모든 ID, 추천/제외의 의미, 저장소별 명령을 생성·실행하지 않는다는 제약을 문서화한다.
- [ ] **Step 2: JSON 안내 문서를 갱신한다.** 루트 README, Codex README, route skill에 JSON의 `verification`이 추천 정보임을 적고 route-file 재생이 그 객체를 실행하지 않는다고 명시한다.
- [ ] **Step 3: 공유 산출물을 동기화한다.** `python3 scripts/sync_bundle.py`를 실행한다.
- [ ] **Step 4: 문서와 bundle을 검증한다.** `python3 scripts/validate_bundle.py`, `python3 -m unittest tests.test_router.BundleParityTests.test_plugin_copies_match_the_bundle_root -v`, `git diff --check`를 실행한다.

### Task 4: 최종 회귀 검증과 커밋

**파일:** Task 1-3의 변경 파일만 포함한다.

**인터페이스:** route-file 재생, 세 플랫폼의 실행 명령, 기존 모델 매핑은 기존 테스트 계약을 유지한다.

- [ ] **Step 1: 전체 검증을 실행한다.** `python3 -m unittest discover -s tests -v`, `python3 scripts/validate_bundle.py`, `git diff --check`, `git status --short`를 실행한다.
- [ ] **Step 2: 변경 범위를 확인한다.** `git diff -- scripts/router.py tests/test_router.py references/routing-policy.md README.md plugins`로 추천 JSON, 문서, 생성 사본 외 변경이 없는지 확인한다.
- [ ] **Step 3: 커밋한다.** 검증이 통과하면 `feat(router): add verification recommendations` 메시지로 커밋한다.

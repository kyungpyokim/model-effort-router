# Glossary

MER(Model Effort Router)의 도메인 용어. 코드와 문서에서 아래 이름을 그대로 쓴다.

## 라우팅

- **MER**: 개발 요청을 role + effort로 분류하고 호스트 모델을 추천한다. 작업·리뷰·수정 실행은 호스트가 담당한다.
- **Main**: 호스트의 메인 세션. 대화 맥락과 작업 흐름을 관리한다.
- **role**: 요청 종류. `implementation`, `fix`, `lint`, `test`, `plan`, `design`, `review`, `analysis`.
- **effort**: 추론 강도. `low` < `medium` < `high` < `xhigh` < `max`. 호스트·lane마다 지원 범위가 다르다.
- **lane**: role이 속하는 모델 계열. `execution`(implementation, fix, lint, test)과 `reasoning`(plan, design, review, analysis).
- **route advice**: hook이 제공하는 role, model, effort 추천. 강제가 아니며 활성 설정을 변경하지 않는다.
- **primary / alternatives**: lane별 추천 모델과 사용자가 선택할 대안 모델.
- **`router.mode`**: `auto`(기본, classifier 사용) 또는 `policy`(classifier 없이 정적 모델 맵 제공).

## 분류

- **classifier / backend**: 요청의 role과 effort를 판단하는 구성요소. `subscription`(기본), `jev`, `openai_decisions`, `nimble`, `laya`.
- **classifier fallback chain**: backend 실패 시 순서대로 시도하는 다음 backend 목록. 모델별 이전 `fallback` 설정은 호환을 위해 읽지만 사용하지 않는다.
- **Jev**: TypeSafe의 호스팅 classifier. 라우팅 여부(`route`/`no_route`)까지 판단한다.
- **Nimble / Laya**: loopback 서버에서 실행할 수 있는 로컬 classifier.
- **risk flag**: backend와 무관하게 규칙으로 탐지하는 안전 신호. `security`, `auth`, `payment`, `data_migration`, `data_loss`, `concurrency`. 보안 민감 review/design 요청의 effort 하한을 올릴 수 있지만 role과 lane은 바꾸지 않는다.

## 검증 도구

- **Test Gate (`gate/`, `mer-gate`)**: 독립 CLI. 저장소의 검증 명령(`test`, `lint`, `typecheck`, `build`)을 찾아 실행하고 check별 `passed`/`failed`/`not_run`을 JSON으로 출력한다.
- **probe (test-without-change)**: 추가·수정한 테스트가 변경 전 코드에서도 통과하는지 확인하는 별도 검사. 보고만 하며 작업 트리와 `.git`은 쓰지 않는다.

## 운영

- **shared runtime / core**: `model_effort_router/` 패키지. 모든 호스트 plugin이 공유하는 단일 코드 원본이며 plugin 디렉터리에는 복사하지 않는다. `scripts/install_core.py`로 설치한다.
- **host plugin**: 호스트별 통합(`plugins/*-model-effort-router`). 매니페스트, hook, skill, launcher만 가진다.
- **host**: MER이 붙는 CLI. `codex`, `claude`, `antigravity`, `opencode`.
- **`MER_CORE_PATH`**: 로컬 개발 시 core를 저장소 루트로 지정하는 환경변수.
- **route log**: 라우팅과 hook이 보고한 호스트 이벤트를 기록하는 로그. 과거 버전의 `run` 항목은 호환성을 위해 읽을 수 있다.

# Glossary

MER(Model Effort Router)의 도메인 용어. 코드와 문서에서 아래 이름을 그대로 쓴다.

## 라우팅

- **MER**: 개발 요청을 role + effort로 분류하고, 그 쌍을 호스트 모델에 매핑하는 도구. 현재 턴의 모델은 바꾸지 않는다.
- **Main**: 호스트의 메인 세션. 대화 맥락을 소유하고, 필요한 단계를 정해 호스트 네이티브 Subagent를 호출한다. MER은 Main을 대신하지 않는다.
- **Subagent**: 호스트 네이티브 서브에이전트. hook advice가 가리킨 모델·effort로 작업을 위임받는다.
- **Worker**: `mer run`이 외부에서 실행하는 단일 작업자. Main의 대화를 읽지 못하므로 필요한 맥락은 task 입력에 명시한다.
- **role**: 요청의 종류. `implementation`, `fix`, `lint`, `test`, `plan`, `design`, `review`, `analysis`.
- **effort**: 추론 강도. `low` < `medium` < `high` < `xhigh` < `max`. 호스트·lane마다 지원 범위가 다르다.
- **lane**: role이 속하는 모델 계열. `execution`(implementation, fix, lint, test)과 `reasoning`(나머지 role).
- **route advice / hook advice**: hook이 Main에 주입하는 권고(role, effort, 모델). 강제가 아니라 조언이며 hook은 실패 시 요청을 막지 않는다(fail open).
- **primary / alternatives / fallback**: lane별 모델 설정. primary는 권장 모델, alternatives는 사용자가 고를 수 있는 후보, fallback은 실행 전 불가 신호가 명시적일 때만 쓰는 대체 모델.
- **`router.mode`**: `auto`(기본, classifier 사용) 또는 `policy`(classifier를 건너뛰고 정적 모델 맵만 주입).
- **Context Packet**: Main이 Subagent에 넘기는 compact 입력(`task`, `context`, `decisions`, `constraints`, `relevant_files`, `expected_result`). hook은 필드와 지침만 주고 채우는 것은 Main이다.

## 분류

- **classifier / backend**: 요청의 role과 effort를 판단하는 구성요소. `subscription`(기본), `jev`, `openai_decisions`, `nimble`, `laya`. worker 모델(`models.<host>`)과는 별개다.
- **fallback chain**: `backend` 실패 시 순서대로 시도하는 다음 backend 목록.
- **Jev**: TypeSafe의 호스팅 classifier. 라우팅 여부(`route`/`no_route`)까지 판단한다.
- **Nimble / Laya**: 로컬(loopback) classifier. 요청이 기기 밖으로 나가지 않는다.
- **`route` / `no_route`**: classifier가 내리는 라우팅 대상 판정. `no_route`면 라우팅하지 않는다.
- **session context**: 짧은 후속 요청("진행해")을 분류하기 위해 Jev에 함께 보내는 세션 요약과 최근 user/assistant 턴(텍스트만).
- **risk flag**: backend와 무관하게 규칙으로 탐지하는 안전 신호. `security`, `auth`, `payment`, `data_migration`, `data_loss`, `concurrency`. review/design 요청을 최소 `high`로 올리지만 role과 lane은 바꾸지 않는다.

## 실행과 검증

- **`mer run`**: 외부 worker 한 개를 실행하는 경로.
- **low-first**: `low`에서 시작해 검증 실패마다 medium, high로 승격하는 실행 방식(`--low-first`).
- **promotion / escalation**: 검증 실패 후 effort를 올리는 것. xhigh와 max 앞에서는 승인 정지(`--approve-xhigh`, `--approve-max`)가 필요하다.
- **`continuation_context`**: 승인 정지 시 반환되는 원 요청과 마지막 실패. 승인 후 같은 workspace에서 이어 실행할 때 쓴다.
- **verify (`--verify`)**: 작업 완료를 판단하는 argv 명령. shell 확장 없이 실행되며 마지막 2,000자가 다음 시도에 전달된다.
- **attempt**: worker의 1회 실행. 시도마다 새 세션을 열고 workspace의 수정은 유지한다.
- **`first_pass`**: 첫 시도에서 검증을 통과했는지 여부.
- **`escalation_count`**: 승격 횟수.
- **Test Gate (`gate/`, `mer-gate`)**: 저장소의 검증 명령(`test`, `lint`, `typecheck`, `build`)을 찾아 실행하고 check별로 `passed`/`failed`/`not_run`을 JSON으로 출력한다. 명령은 config → AGENTS.md/CLAUDE.md → CI 파일 → manifest 순으로 탐색하며, 선언된 적 없는 check는 `not_run`이지 `passed`가 아니다.
- **probe (test-without-change)**: 이번 실행이 추가·수정한 테스트가 변경 전 코드에서도 통과하는지 확인한다. 보고만 하며 작업 트리와 `.git`은 쓰지 않는다.
- **review verdict**: 독립 리뷰의 결과. `VERDICT: approved | changes_requested`, 파싱할 수 없으면 `unknown`. `FINDINGS: <n>`이 함께 온다.

## 운영

- **shared runtime / core**: `model_effort_router/` 패키지. 모든 호스트 plugin이 공유하는 단일 코드 원본이며 plugin 디렉터리에 복사하지 않는다. `scripts/install_core.py`로 설치한다.
- **host plugin**: 호스트별 통합(`plugins/*-model-effort-router`). 매니페스트, hook, skill, launcher만 가진다.
- **host**: MER이 붙는 CLI. `codex`, `claude`, `antigravity`, `opencode`. Antigravity와 OpenCode는 route advice만 제공하고 worker 실행은 지원하지 않는다.
- **`MER_CORE_PATH`**: 로컬 개발·테스트 시 core를 저장소 루트로 지정하는 환경변수.
- **route log**: 시도 메타데이터, 토큰 수, 검증 상태/소요 시간만 남기는 영속 로그. 검증 출력 본문은 저장하지 않는다.

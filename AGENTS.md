# AGENTS.md

구현 세션과 독립 리뷰 세션이 모두 읽는 저장소 규칙. 짧게 유지한다.

## Retro 규칙

사람 리뷰에서 나온 지적을 다음 에이전트 실행에 되먹인다.

- 같은 지적이 두 번 나오면 아래 "코딩 기준"에 한 줄로 추가한다.
- 테스트·lint·`scripts/` 검사로 결정적으로 잡을 수 있으면 규칙 대신 검사를 추가하고, 여기서는 지운다.
- 에이전트가 파일을 찾느라 헤맸으면 "탐색 포인터"에 경로 한 줄을 추가한다.
- 더 이상 맞지 않는 줄은 지운다. 한 줄에 규칙 하나, 이유는 짧게.

## 코딩 기준

- `model_effort_router/`를 고치면 `python3 scripts/sync_plugin.py`로 `plugins/*/` 번들을 동기화한다 (테스트가 차이를 잡는다).

## 탐색 포인터

- 실행 흐름 (구현 → Test Gate → 에스컬레이션 → 독립 리뷰): `model_effort_router/flow.py`
- 리뷰 프롬프트와 판정 파싱: `model_effort_router/review.py`
- 리뷰를 붙일지, 어느 프로필로 돌릴지: `model_effort_router/policy/session.py`
- 위험 플래그 정규식: `model_effort_router/difficulty/risk.py`

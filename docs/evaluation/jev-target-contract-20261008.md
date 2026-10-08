# Jev target 계약 수정과 프로젝트 정보 전달

2026-10-08, branch `codex/jev-target-contract`. 원시 질문, 입력 state, 응답, 재시도 기록은 [JSON](jev-target-contract-20261008.json)에 있다. 인증 헤더와 사용자 대화는 포함하지 않았다.

## 문제와 변경

`현재 진행 상황 파악`은 Jev를 거쳤지만 `target=no_route`로 판단됐다. 기존 기준은 개발 작업 여부를 물었고, 첫 요청의 state에는 프로젝트 정보가 없었다. 프로젝트 이름만 추가한 이전 반복 비교에서도 `no_route`가 유지됐다. API는 내부 판단 이유를 반환하지 않으므로 특정 내부 원인을 확정할 수는 없다.

수정은 다음 두 가지다.

- `target` 기준을 현재 프로젝트에서 요청한 결과로 교체했다. 조사·현황 분석·동작 설명도 작업이며, 단순 승인에는 세션 맥락에 실행 가능한 제안이 있어야 한다.
- 훅과 CLI의 작업 디렉터리 basename을 기존 `DifficultyInput.repo_summary`로 전달한다. 공통 state에 `Active project`를 넣되 기존 4,000자 제한을 적용한다. 프로젝트 정보는 생략된 대상만 보충한다.

target criteria의 개별 요청 예시는 제거했다. 기존 공통 세션 지시문과 role/effort 질문은 유지했다. target의 Unicode JSON 직렬화 길이는 기존 1,109자에서 최종 984자로 줄었다(`ensure_ascii=False`; 토큰 수를 뜻하지 않는다). fallback과 모델 매핑은 변경하지 않았다.

## 실제 호출 비교

변경 기준을 호출하기 전에 구현 담당 에이전트가 한국어/영어 각 10건의 기대 target을 정했다. 개발 작업 12건과 인사·감사·날씨·제안 없는 승인 8건이다. 경로와 세션 맥락은 비웠고, 프로젝트 정보가 있는 조건에는 `model-effort-router-next`를 넣었다. 요청 모델은 `jev-latest`, 응답 모델은 `jev-1.13.0`이었다.

| 조건 | 기대 target과 일치 | 실제 API 호출 | 불일치 |
|---|---:|---:|---|
| 기존 기준, 프로젝트 정보 없음 | 18/20 | 23 | 한국어·영어 진행 상황 요청 |
| 기존 기준, 프로젝트 정보 있음 | 19/20 | 20 | 한국어 진행 상황 요청 |
| 첫 수정 기준, 프로젝트 정보 없음 | 20/20 | 20 | 없음 |
| 첫 수정 기준, 프로젝트 정보 있음 | 19/20 | 22 | 제안 없는 `승인`이 route |
| 최종 기준, 프로젝트 정보 있음 | 22/22 | 23 | 없음 |

첫 수정에서는 프로젝트 정보가 실행 제안으로 해석될 여지가 드러났다. 메타데이터는 대상만 제공하고, 승인은 세션의 실행 가능한 제안을 요구하도록 일반 기준을 보완했다. 최종 측정은 같은 20건에 실행 제안이 있는 한국어/영어 승인 2건을 더했다. HTTP 503은 비교 단계 5회, 최종 단계 1회였으며 제한된 재시도로 모두 복구됐다. 운영 코드에 재시도를 추가하지 않았다.

최종 `현재 진행 상황 파악`의 raw target은 `route`, confidence 0.98, P(route) 0.99였다. 제안 없는 `승인`은 `no_route`, P(route) 0.03이었다. 설치된 코어를 저장소 밖에서 import한 뒤 원래 요청의 줄바꿈까지 포함한 `현재 진행 상황 파악\n`을 실제 router에 세 번 넣어 모두 `route / analysis / gpt-6.1-sol`을 확인했다. 같은 설치본의 제안 없는 승인은 `no_route`였다. 총 112회 API 호출이며 설치본 확인 4회에는 재시도가 없었다.

**이 결과는 작은 합성 진단·조정 세트의 관찰이다.** 라벨은 구현 담당 에이전트가 작성했고, 동일한 사례를 기준 보완에 재사용했다. 독립 holdout 또는 일반 분류 정확도 100%를 뜻하지 않는다. 내부 판단 이유도 여전히 관찰할 수 없다.

## 구현 검증

계획은 전달 경로와 분류 계약의 회귀 검사 → 최소 코어 수정 → 실제 호출 비교 → 검토와 설치 순서였다.

- RED checkpoint `aa7098a`: 84개 집중 검사에서 의도한 3개 실패와 4개 오류를 확인했다. 훅/CLI → router → backend state의 프로젝트 정보 전달과 target 계약을 검증한다.
- 첫 승인 오분류를 발견한 뒤 metadata/proposal 구분 검사도 먼저 실패시키고 기준을 보완했다. GREEN 집중 검사 84개 통과.
- 최종 전체 검사: `MER_CORE_PATH="$PWD" python3 -m unittest discover -s tests`, 509개 통과. 실제 실행은 임시 coverage 환경에서 같은 suite를 측정했다.
- 변경 런타임 4파일 합산 line coverage 87%: CLI 83%, Jev 90%, 훅 92%, router 90%. 저장소 전체 커버리지 수치가 아니다.
- 독립 코드·Python·보안 검토에서 차단할 문제 없음. 변경 파일 Ruff와 `git diff --check` 통과.
- `env -u MER_CORE_PATH python3 scripts/install_core.py` 완료. `--check` 결과 `in sync`. 설치본의 실제 호출 결과는 JSON의 `installed_runtime_verification`에 있다.

기존 `test_context_refresh.py`의 unclosed-file ResourceWarning은 남아 있지만 검사 실패는 없었다. 운영 설정이나 자격 증명은 변경하지 않았다.

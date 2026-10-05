# L2 경계 질문과 Jev 조건부 재판정 — 2026-10-04 UTC

**결론: 새 L2 질문은 기각한다.** Nimble L2 38/49→35/49, 전체 220/250→213/250, critical miss 6→8건이다. 이전 보강 질문을 사용한 조건부 Jev 재판정은 아래 두 규칙에서 사전 기준을 통과했다. 제품 질문·임계값·라우팅 코드는 변경하지 않았다.

## 실험 조건

- corpus-v2 300건에서 Jev 300회, Nimble 300회 **새 live 호출 600회**. HTTP 200 600회, transport error 0, fallback 0. 레벨 평가는 250건, target은 300건, critical 판정 대상은 128건.
- 기존 보강 질문의 L2 criterion 하나만 바꿨다. instructions와 나머지 네 criterion, 비레벨 질문, 모델·옵션·후처리 임계값을 유지했다. 이전 보강 실측을 역사적 대조군으로 사용했으며 새 무작위 A/B가 아니다. 단일 실행 차이를 통계적 인과 증명으로 해석하지 않는다.
- 사전 계획: `runs/l2-boundary-experiment-plan-20261004.json`. 통과 기준은 합본의 모든 레벨 정확도 ≥80%, critical miss ≤2건(제품 기본 Nimble 기준). 이는 Jev 기본의 0건과 동등하다는 기준은 아니다.
- 정답은 합성 사례의 AI 합의 라벨이다. 사람 검증 전이며, 모두 이전 평가에 노출된 사례라 독립 holdout이 아니다. 입력은 task와 paths이고 실제 코드·diff는 제공하지 않았다.

변경한 L2 criterion:

L2 local judgment within existing structure: read and reason about an existing function, handler, query, component lifecycle or build step to fix behavior or add a small option. Prescribed desired behavior still requires L2 when correctness depends on implementation logic. Preserve existing interfaces; multiple call sites with fixed mappings remain L2. Use L3 when coordinating contracts across distinct layers, rather than merely touching several files. Rate a review by the underlying change scope, not by the domain or filename.

## 새 live 결과

| 정답 레벨 | Jev 이전 보강 | Jev L2 후보 | Nimble 이전 보강 | Nimble L2 후보 |
|---|---:|---:|---:|---:|
| L1 | 49/51 (96.1%) | 50/51 (98.0%) | 48/51 (94.1%) | 47/51 (92.2%) |
| L2 | 46/49 (93.9%) | 47/49 (95.9%) | 38/49 (77.6%) | 35/49 (71.4%) |
| L3 | 49/50 (98.0%) | 47/50 (94.0%) | 42/50 (84.0%) | 42/50 (84.0%) |
| L4 | 45/50 (90.0%) | 44/50 (88.0%) | 45/50 (90.0%) | 42/50 (84.0%) |
| L5 | 48/50 (96.0%) | 48/50 (96.0%) | 47/50 (94.0%) | 47/50 (94.0%) |
| 전체 | 237/250 (94.8%) | 236/250 (94.4%) | 220/250 (88.0%) | 213/250 (85.2%) |

| 조건 | target | 과대/과소 | critical miss | 실제 p50 ms |
|---|---:|---:|---:|---:|
| jev baseline | 294/300 (98.0%) | 13/7 | 0/128 | 243 |
| nimble baseline | 289/300 (96.3%) | 14/36 | 2/128 | 984 |
| jev guide | 294/300 (98.0%) | 4/9 | 1/128 | 247 |
| nimble guide | 289/300 (96.3%) | 12/18 | 6/128 | 1245 |
| jev l2-boundary | 294/300 (98.0%) | 4/10 | 2/128 | 242 |
| nimble l2-boundary | 288/300 (96.0%) | 11/26 | 8/128 | 1079 |

L2 국소 판단 문장을 명확하게 쓰는 것만으로 개선되지 않았다. Jev는 L2 1건을 더 맞혔지만 다른 레벨 회귀로 전체는 1건 감소했다. Nimble은 L2에서 2건 개선·5건 회귀했다. 단순 승격 임계값 조정만으로 이 문제를 해결한다는 근거도 없다.

## Nimble L2에서 바뀐 정답/오답

| ID | 변화 | 이전→후보 | 요청 |
|---|---|---|---|
| seed-016 | 회귀 | L2→L1 | Replace the ad-hoc logging calls in the worker modules with the structured logger and keep the log fields stable |
| exp-018 | 개선 | L1→L2 | 화면 회전하면 ViewModel에서 목록이 두 번 로드돼. 한 번만 로드되게 고쳐줘. |
| exp-026 | 회귀 | L2→L1 | 학습 루프에 --max-grad-norm 옵션으로 gradient clipping 추가해줘. |
| exp-029 | 회귀 | L2→L1 | Rename the CLI option `--retries` to `--max-retries` in the command, its help text and the docs, keeping the old name as a hidden alias. |
| exp-068 | 회귀 | L2→L1 | Replace the ~40 logger.info(...) calls with the new log_event() helper, keeping the same fields as today. |
| add-029 | 회귀 | L2→L1 | Tkinter 저장 버튼이 한 번 클릭하면 두 번 연결된 callback을 실행한다. 초기화 함수의 중복 bind를 제거해줘. |
| add-034 | 개선 | L3→L2 | Review only: a patch swaps two arguments to the existing payment SDK refund call in refunds.py. The approved SDK contract is attached and no workflow changes are intended. |

## 새 후보의 80% 미만 구간 전체 확인

합본뿐 아니라 기존 v1/추가분을 확인했다. Jev 후보는 모든 구간이 80% 이상이다. 아래는 Nimble 후보의 80% 미만 구간이다.

| 범위 | 레벨 | 정확도 |
|---|---|---:|
| 합본 | L2 | 35/49 (71.4%) |
| 기존 v1 | L2 | 22/32 (68.8%) |
| 기존 v1 | L3 | 27/34 (79.4%) |
| 추가분 | L2 | 13/17 (76.5%) |

해당 구간의 모든 오답을 중복 없이 표시했다. 확률은 모델의 실제 출력이며 보정된 정답 확률로 간주하지 않는다.

| ID | 구간 | 정답→후보 | raw argmax | top 확률 | 요청 |
|---|---|---|---|---:|---|
| seed-016 | 합본, 기존 v1 | L2→L1 | L1 | 0.611 | Replace the ad-hoc logging calls in the worker modules with the structured logger and keep the log fields stable |
| seed-033 | 기존 v1 | L3→L2 | L2 | 0.794 | 계획만 세워줘: 테스트 스위트를 병렬 실행으로 바꾸는 방법 |
| seed-034 | 기존 v1 | L3→L2 | L2 | 0.678 | Draft a plan for adding OAuth login to the web app, then wait for my approval |
| seed-035 | 합본, 기존 v1 | L2→L3 | L3 | 0.701 | Review only: look at the changes in api/upload.py for bugs, do not modify anything |
| seed-036 | 기존 v1 | L3→L5 | L3 | 0.398 | 리뷰만 해줘. 방금 바꾼 결제 모듈 코드에 문제가 없는지 검토해줘 |
| exp-007 | 기존 v1 | L3→L2 | L2 | 0.838 | Airflow DAG에 증분 로딩 추가해줘. 먼저 어떻게 할지 계획을 보여주고 내가 OK 하기 전에는 코드 건드리지 마. |
| exp-014 | 합본, 기존 v1 | L2→L3 | L3 | 0.939 | Review this profile image upload code (type sniffing, 5MB cap, S3 storage) for problems. Don't change anything. |
| exp-019 | 합본, 기존 v1 | L2→L1 | L1 | 0.674 | 개발용 Docker Compose에 Postgres, Redis, 마이그레이션 컨테이너 추가하고 헬스체크 기준으로 기동 순서 맞춰줘. |
| exp-026 | 합본, 기존 v1 | L2→L1 | L1 | 0.500 | 학습 루프에 --max-grad-norm 옵션으로 gradient clipping 추가해줘. |
| exp-029 | 합본, 기존 v1 | L2→L1 | L1 | 0.636 | Rename the CLI option `--retries` to `--max-retries` in the command, its help text and the docs, keeping the old name as a hidden alias. |
| exp-039 | 기존 v1 | L3→L1 | L1 | 0.525 | 장바구니랑 위시리스트 상태를 Redux에서 Zustand로 바꿔줘. 컴포넌트 여러 개 걸려 있어. |
| exp-041 | 기존 v1 | L3→L1 | L1 | 0.459 | Convert the iOS app's networking layer from completion handlers to async/await across all 9 service classes, with proper cancellation. |
| exp-062 | 합본, 기존 v1 | L2→L3 | L3 | 0.664 | Check reports/monthly.sql: customers with no refunds seem to vanish. Review only, tell me what's wrong and don't edit. |
| exp-064 | 합본, 기존 v1 | L2→L1 | L1 | 0.726 | Set up a GitHub Actions matrix for Python 3.10-3.12 with a shared cached venv and a separate lint job, and make release.yml depend on both. |
| exp-068 | 합본, 기존 v1 | L2→L1 | L1 | 0.817 | Replace the ~40 logger.info(...) calls with the new log_event() helper, keeping the same fields as today. |
| exp-087 | 기존 v1 | L3→L1 | L1 | 0.702 | Move our CI from Jenkins to GitHub Actions: build, test, deploy stages with environment secrets and approval gates. |
| exp-092 | 합본, 기존 v1 | L2→L1 | L1 | 0.608 | GitHub Actions에 pip 캐시 단계 넣어서 CI 시간 줄여줘. |
| add-029 | 합본, 추가분 | L2→L1 | L1 | 0.605 | Tkinter 저장 버튼이 한 번 클릭하면 두 번 연결된 callback을 실행한다. 초기화 함수의 중복 bind를 제거해줘. |
| add-035 | 합본, 추가분 | L2→L1 | L1 | 0.647 | 이미 soft-delete 필터가 있는 repository에서 count() 한 메서드만 필터를 누락했다. 다른 조회들과 같은 조건을 적용해줘. |
| add-041 | 합본, 추가분 | L2→L1 | L1 | 0.730 | Remove password values from this single debug log statement, retaining the user ID and error code; the log schema is already fixed. |
| add-042 | 합본, 추가분 | L2→L3 | L3 | 0.804 | Review only: check this SQL query's LEFT JOIN predicate placement against the attached requirement to retain zero-match suppliers. No schema changes. |

## Nimble 후보 critical miss 8건

critical miss는 정답 L4/L5 또는 위험 플래그가 있는 사례에서 정답보다 낮고 L2 이하로 예측한 경우다. 사례별 피해 크기가 같다는 뜻은 아니다.

| ID | 정답→후보 | 이전에도 critical | 요청 |
|---|---|---|---|
| seed-034 | L3→L2 | 예 | Draft a plan for adding OAuth login to the web app, then wait for my approval |
| exp-035 | L4→L1 | 예 | DB 읽기 replica를 도입하고 조회 쿼리는 replica로 보내도록 데이터 접근 계층을 바꿔줘. |
| exp-041 | L3→L1 | 아니오 | Convert the iOS app's networking layer from completion handlers to async/await across all 9 service classes, with proper cancellation. |
| exp-079 | L4→L2 | 아니오 | 공개 SDK 인증을 API key에서 OAuth2 client credentials로 바꾸고, 기존 key도 6개월은 지원해야 해. |
| exp-087 | L3→L1 | 예 | Move our CI from Jenkins to GitHub Actions: build, test, deploy stages with environment secrets and approval gates. |
| add-041 | L2→L1 | 예 | Remove password values from this single debug log statement, retaining the user ID and error code; the log schema is already fixed. |
| add-070 | L4→L1 | 예 | Add an explicit process supervisor to the existing single-process monitoring tool so collectors run in isolated child processes with a defined restart and result protocol. |
| add-113 | L5→L2 | 예 | Plan only: redesign the hospital event reconciliation that currently associates sensor readings with the wrong patient only after reconnect bursts. Find a way to prove identity associations remain correct. |

## 미리 고정한 Jev 재판정 규칙

1. `uncertain`: Nimble raw top 확률 <0.60 **또는** top 두 확률 차이 <0.15.
2. `uncertain_or_scoped`: 1 또는 Nimble **예측** target이 plan_only/review_only.
3. `uncertain_or_scoped_or_risk`: 2 또는 Nimble backend/regex 위험 플래그 존재.

선택에는 정답 라벨을 사용하지 않았다. 선택 시 Jev의 레벨·target·위험 플래그로 재판정한다. 각 질문 조건 안에서 Jev/Nimble의 같은 입력에 대한 저장된 live 결과를 재생했다. 추가 API 호출은 0회이며 실제 연쇄 라우터를 실행한 결과는 아니다. 규칙·숫자는 결과를 보기 전에 고정했다. 이전 보강과 새 후보에 동일한 규칙을 적용했다.

| 질문 | 규칙 | 전체 정확도 | L2 | critical | Jev 호출 | 전체 추론 호출 | 순차 transport p50 추정 ms | 통과 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| guide | uncertain | 227/250 (90.8%) | 40/49 (81.6%) | 3/128 | 46/300 (15.3%) | 346 | 1253 | 실패 |
| guide | uncertain_or_scoped | 236/250 (94.4%) | 44/49 (89.8%) | 2/128 | 101/300 (33.7%) | 401 | 1269 | 통과 |
| guide | uncertain_or_scoped_or_risk | 237/250 (94.8%) | 44/49 (89.8%) | 1/128 | 168/300 (56.0%) | 468 | 1449 | 통과 |
| l2-boundary | uncertain | 219/250 (87.6%) | 36/49 (73.5%) | 4/128 | 45/300 (15.0%) | 345 | 1127 | 실패 |
| l2-boundary | uncertain_or_scoped | 228/250 (91.2%) | 40/49 (81.6%) | 3/128 | 100/300 (33.3%) | 400 | 1151 | 실패 |
| l2-boundary | uncertain_or_scoped_or_risk | 229/250 (91.6%) | 40/49 (81.6%) | 2/128 | 164/300 (54.7%) | 464 | 1213 | 통과 |

추정 지연은 각 사례의 Nimble transport 시간에, 선택된 사례의 Jev transport 시간을 더한 값의 중앙값이다. 서로 다른 실행의 시간 합이며 실제 운영 latency나 큐 지연을 측정한 값이 아니다. Jev 단독(이전 보강)은 실제 p50 247ms여서 이 측정에서 혼합 방식이 더 빠르다는 근거는 없다. Jev API 호출 절감률만 계산했으며 전체 비용·로컬 연산 비용·토큰 비용 절감으로 바꾸어 말하지 않는다.

### 통과 조합의 레벨별 결과

| 레벨 | guide + scoped | guide + scoped + risk | 새 후보 + scoped + risk |
|---|---:|---:|---:|
| L1 | 51/51 (100.0%) | 51/51 (100.0%) | 50/51 (98.0%) |
| L2 | 44/49 (89.8%) | 44/49 (89.8%) | 40/49 (81.6%) |
| L3 | 48/50 (96.0%) | 49/50 (98.0%) | 47/50 (94.0%) |
| L4 | 45/50 (90.0%) | 45/50 (90.0%) | 44/50 (88.0%) |
| L5 | 48/50 (96.0%) | 48/50 (96.0%) | 48/50 (96.0%) |

### 통과 조합에서 남은 critical

| 조합 | ID | 사용한 예측 | 정답→예측 | Nimble raw top 확률 | margin |
|---|---|---|---|---:|---:|
| guide uncertain_or_scoped | exp-087 | nimble | L3→L1 | 0.662 | 0.531 |
| guide uncertain_or_scoped | add-041 | jev | L2→L1 | 0.539 | 0.119 |
| guide uncertain_or_scoped_or_risk | add-041 | jev | L2→L1 | 0.539 | 0.119 |
| l2-boundary uncertain_or_scoped_or_risk | seed-036 | jev | L3→L2 | 0.398 | 0.063 |
| l2-boundary uncertain_or_scoped_or_risk | add-041 | jev | L2→L1 | 0.730 | 0.508 |

불확실한 요청만 재판정한 규칙은 두 질문 모두 critical 기준을 실패했다. 확신 있게 틀리는 사례가 남으므로 모델 확률 하나만으로 재판정 여부를 정하면 놓칠 수 있다. 위험 플래그까지 추가한 이전 보강 조합은 Jev 단독 보강과 같은 전체 정확도·critical 수를 기록했지만 개별 오답은 같지 않다.

## 사람 정답 검토와 다음 검증

- [40건 독립 검토 시트](../../evaluation/corpus/human-review-v2-boundaries.tsv): L1 10건, L2 20건, L3 10건. 기존 라벨·모델 예측 없이 task/paths만 제공했고 labeler/level/risk_flags/target/note는 모두 비워 두었다. **사람 검토는 아직 수행되지 않았다.** AI가 대신 채워서 사람 검토 완료로 처리하지 않았다.
- 정확도 우선이면 Jev 단독이 단순한 선택이다. 현재 제품 질문의 Jev는 전체 92.0%, critical 0건이다. 보강 Jev는 94.8%, critical 1건이라 보강을 자동 채택할 근거로 평균 정확도만 사용하지 않는다.
- Jev 호출 절감이 목표면 이전 보강 + uncertain_or_scoped_or_risk를 후속 검증 후보로 둔다. Jev 168/300회로 단독 대비 API 호출 44.0% 감소, 전체 94.8%, critical 1건이다. 더 적게 호출하는 scoped 조합은 101/300회, 94.4%, critical 2건이다.
- 채택 전 필요한 것은 사람의 경계 라벨 검토, 이번 조정에 사용하지 않은 실제 요청 holdout, 실제 연쇄 호출의 지연·실패 처리 검증이다. 새 L2 문구를 더 길게 늘리거나 현 코퍼스로 임계값을 다시 맞추는 작업은 진행하지 않았다.

## 원자료

- 계획: `runs/l2-boundary-experiment-plan-20261004.json`
- 이전/새 질문: `runs/live-guide-level-question-20261004.json`, `runs/live-l2-boundary-question-20261004.json`
- 새 live 결과와 metadata: `runs/compare-v2-live-l2-boundary-{jev,nimble}-20261004{,-metadata}.json`
- 혼합 재생 결과(예측·선택 ID 포함): `runs/hybrid-replay-v2-20261004.json`
- 코퍼스 SHA-256: `ebb44941bc42a8c6b14d89077c4ca43a36aeb1c888a1905a4b1796cf739862f5`

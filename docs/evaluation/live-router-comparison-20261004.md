# Jev / Nimble live 비교 — 2026-10-04

동일 corpus-v1 150건을 backend 2종 × 질문 2종으로 호출했다. 총 600 live 분류 요청, 레벨 평가는 각 조건 130건, target 평가는 150건. 네 조건 모두 fallback 0건. 제품 코드는 변경하지 않았다.

기존 질문은 저장소 CLI `evaluation.compare --live`로 호출했고, 보강 질문은 동일 평가 도구와 backend를 사용하면서 transport에 보내는 `questions.level`만 교체했다. 모델 설정, target/risk 질문, 보정 임계값, corpus는 동일하다. Nimble 로컬 호출을 겹치지 않았다.

보강 질문은 기존 라벨 가이드의 판단량, 구현 난이도 기준(plan/review 포함), 기능 추가 대 구조 변경, 원인 불명의 복합 장애, 보안 핵심 재작성, 무손실 migration 앵커를 명시한다. 정확한 질문은 `runs/live-guide-level-question-20261004.json`. 각각의 변경 문장이 기여한 양은 분리 측정하지 않았다.

## 레벨별 정확도

| 레벨 | n | Jev 기존 live | Jev 보강 live | Nimble 기존 live | Nimble 보강 live |
|---|---:|---:|---:|---:|---:|
| L1 | 26 | 25/26 (96.2%) | 25/26 (96.2%) | 24/26 (92.3%) | 25/26 (96.2%) |
| L2 | 32 | 24/32 (75.0%) | 30/32 (93.8%) | 23/32 (71.9%) | 25/32 (78.1%) |
| L3 | 34 | 30/34 (88.2%) | 34/34 (100.0%) | 30/34 (88.2%) | 27/34 (79.4%) |
| L4 | 23 | 22/23 (95.7%) | 22/23 (95.7%) | 16/23 (69.6%) | 21/23 (91.3%) |
| L5 | 15 | 11/15 (73.3%) | 13/15 (86.7%) | 8/15 (53.3%) | 13/15 (86.7%) |
| 전체 | 130 | 112/130 (86.2%) | 124/130 (95.4%) | 101/130 (77.7%) | 111/130 (85.4%) |

## 부작용·비용·속도

| 조건 | 과대 / 과소 | 중대 과소 | target 정확도 | 세션 프로필 일치 | 위험 신호 재현율 / 정밀도 (정규식 병합) | p50 ms | 입력 / 출력 토큰 |
|---|---:|---:|---:|---:|---:|---:|---:|
| jev 기존 | 12 / 6 | 0/58 | 147/150 | 93/130 | 92.9% / 56.5% | 243 | 108,953 / 24,638 |
| jev 보강 | 3 / 3 | 0/58 | 147/150 | 104/130 | 95.7% / 58.3% | 240 | 160,103 / 24,638 |
| nimble 기존 | 8 / 21 | 1/58 | 146/150 | 92/130 | 95.7% / 60.9% | 845 | 905,946 / 1,350 |
| nimble 보강 | 7 / 12 | 3/58 | 145/150 | 104/130 | 92.9% / 61.9% | 1186 | 1,300,746 / 1,350 |

중대 과소 = 정답이 L4/L5 또는 위험 플래그가 있고, 예측이 정답보다 낮으면서 L2 이하인 경우. 위험 질문 자체를 바꾸지 않아도 전체 요청의 level 질문 문맥이 달라지면 risk 출력도 달라질 수 있다. API 청구 금액은 측정하지 않았다.

## 관찰과 판단

- 기존 Nimble live 예측은 이전 `compare-v1-nimble2.json`과 150건 모두 동일했다(확률·risk 점수 포함). 낮은 L5 정확도는 저장 기록에서만 생긴 문제가 아니었다.
- Jev 기존 live는 112/130(86.2%)로, 이전 확률에 현재 정책을 재생한 113/130과 한 건 차이다. 기존 live에서 L4 PK migration seed-026이 L3로 판정됐다. 이 정도 차이는 한 번의 실험에서 보인다.
- 보강 후 Jev는 오답 14건을 맞히고 정답 2건을 틀려 순증 +12건, Nimble은 19건 개선·9건 악화로 순증 +10건이다.
- 두 backend 모두 보강 후 L5 13/15. Nimble이 새로 맞힌 기존 L5 오답은 seed-027(키 회전), seed-028(복합 이중 결제), exp-004(크래시 후 이중 지급), exp-069(부하 시 이중 결제), exp-076(JWT 리뷰) 5건이다. 이 실험은 L5 저평가에 질문 기준이 상당히 기여했음을 뒷받침한다. 모델 크기 자체가 유일한 원인이라는 근거는 없다.
- 양쪽 모두 남은 L5 오류는 exp-043(이벤트 저장소 schema upgrade·무손실 replay)와 exp-090(PK UUID 전환·6개 FK·온라인 backfill)을 L4로 보는 것. 후자는 보강 후 Nimble P(L4)=0.409918 / P(L5)=0.409015로 매우 근접하지만 argmax와 승격의 현재 선택 규칙상 L4가 된다.
- Nimble 보강은 L4/L5를 개선했지만 L3 30→27, 중대 과소 1→3, target 정답 146→145, 위험 재현율 95.7%→92.9%로 악화됐다. 전체 정확도 상승만으로 바로 기본 질문을 교체할 근거는 부족하다.
- Jev 보강은 모든 레벨이 80% 이상이고 중대 과소 0을 유지했다. 다만 같은 코퍼스의 오류를 보고 질문을 만든 단일 A/B이므로 holdout과 반복 측정으로 검증해야 한다.
- 입력 토큰은 Jev 108,953→160,103(+46.9%), Nimble 905,946→1,300,746(+43.6%)로 증가했고 Nimble 중앙 지연은 845→1,186ms로 증가했다. 보강의 정확도 이익에 따른 overhead다.

## 중대 과소 3건 (Nimble 보강)

| ID | 정답 | 기존→보강 | 요청 |
|---|---|---|---|
| seed-034 | L3 | L3→L2 | Draft a plan for adding OAuth login to the web app, then wait for my approval |
| exp-035 | L4 | L3→L1 | DB 읽기 replica를 도입하고 조회 쿼리는 replica로 보내도록 데이터 접근 계층을 바꿔줘. |
| exp-087 | L3 | L3→L1 | Move our CI from Jenkins to GitHub Actions: build, test, deploy stages with environment secrets and approval gates. |

## 판정이 바뀐 케이스

이 표는 레벨의 정답 여부가 바뀐 모든 케이스를 담는다. 단지 오답 레벨이 다른 오답으로 바뀐 경우는 원본 JSON에 있다.

| Backend | ID | 정답 | 기존→보강 | 결과 | 요청 |
|---|---|---|---|---|---|
| jev | seed-016 | L2 | L3→L2 | 개선 | Replace the ad-hoc logging calls in the worker modules with the structured logger and keep the log fields stable |
| jev | seed-026 | L4 | L3→L4 | 개선 | Migrate the orders table to a new schema with a changed primary key; write the migration and backfill |
| jev | seed-034 | L3 | L4→L3 | 개선 | Draft a plan for adding OAuth login to the web app, then wait for my approval |
| jev | seed-036 | L3 | L5→L3 | 개선 | 리뷰만 해줘. 방금 바꾼 결제 모듈 코드에 문제가 없는지 검토해줘 |
| jev | exp-004 | L5 | L4→L5 | 개선 | The partner payout job sometimes sends payouts twice after a crash mid-batch. Make it crash-safe and reconcile what already went out. |
| jev | exp-014 | L2 | L3→L2 | 개선 | Review this profile image upload code (type sniffing, 5MB cap, S3 storage) for problems. Don't change anything. |
| jev | exp-026 | L2 | L3→L2 | 개선 | 학습 루프에 --max-grad-norm 옵션으로 gradient clipping 추가해줘. |
| jev | exp-029 | L2 | L3→L2 | 개선 | Rename the CLI option `--retries` to `--max-retries` in the command, its help text and the docs, keeping the old name as a hidden alias. |
| jev | exp-037 | L4 | L4→L5 | 악화 | A flaky test turned out to be a real race: two workers sometimes both acquire the same lease and double-process a job. Find the root cause and fix it. |
| jev | exp-042 | L5 | L4→L5 | 개선 | 동시 주문이 몰릴 때만 재고가 가끔 음수가 돼. 재현이 잘 안 돼. 원인 찾아서 고쳐줘. |
| jev | exp-043 | L5 | L5→L4 | 악화 | Redesign the event-sourcing store so snapshots and replay stay consistent across a schema upgrade, without losing any events. |
| jev | exp-056 | L3 | L5→L3 | 개선 | GDPR 삭제 요청이 오면 연관 테이블 5곳에서 개인정보를 익명화하거나 삭제하는 배치 작업을 추가해줘. |
| jev | exp-064 | L2 | L3→L2 | 개선 | Set up a GitHub Actions matrix for Python 3.10-3.12 with a shared cached venv and a separate lint job, and make release.yml depend on both. |
| jev | exp-068 | L2 | L3→L2 | 개선 | Replace the ~40 logger.info(...) calls with the new log_event() helper, keeping the same fields as today. |
| jev | exp-069 | L5 | L3→L5 | 개선 | 부하 걸릴 때만 가끔 주문이 두 번 결제돼. 로그엔 같은 payment_intent로 요청이 2번 찍혀. 원인 찾고 고쳐줘. |
| jev | exp-110 | L3 | L4→L3 | 개선 | 프로젝트 하위 라우트 전체에 admin/editor/viewer 역할별 접근 제어를 적용하는 계획만 세워줘. 구현은 하지 마. |
| nimble | seed-004 | L1 | L3→L1 | 개선 | Update the copyright year in every file header under src/ to 2026 |
| nimble | seed-012 | L1 | L2→L1 | 개선 | Bump the retry count in the HTTP client wrapper from 3 to 5 and adjust its unit test |
| nimble | seed-016 | L2 | L3→L2 | 개선 | Replace the ad-hoc logging calls in the worker modules with the structured logger and keep the log fields stable |
| nimble | seed-024 | L4 | L3→L4 | 개선 | Introduce an event bus between the order and notification services and migrate direct calls to events |
| nimble | seed-026 | L4 | L5→L4 | 개선 | Migrate the orders table to a new schema with a changed primary key; write the migration and backfill |
| nimble | seed-027 | L5 | L4→L5 | 개선 | Rewrite the authentication token signing and verification to rotate keys without invalidating live sessions |
| nimble | seed-028 | L5 | L3→L5 | 개선 | Intermittent double charges appear under load; find the root cause across the payment, queue and retry code and fix it |
| nimble | seed-034 | L3 | L3→L2 | 악화 | Draft a plan for adding OAuth login to the web app, then wait for my approval |
| nimble | seed-035 | L2 | L2→L3 | 악화 | Review only: look at the changes in api/upload.py for bugs, do not modify anything |
| nimble | seed-036 | L3 | L3→L5 | 악화 | 리뷰만 해줘. 방금 바꾼 결제 모듈 코드에 문제가 없는지 검토해줘 |
| nimble | exp-004 | L5 | L4→L5 | 개선 | The partner payout job sometimes sends payouts twice after a crash mid-batch. Make it crash-safe and reconcile what already went out. |
| nimble | exp-012 | L3 | L3→L4 | 악화 | Add a nightly worker that emails digests via the queue. Two workers must never send the same digest. |
| nimble | exp-018 | L2 | L2→L1 | 악화 | 화면 회전하면 ViewModel에서 목록이 두 번 로드돼. 한 번만 로드되게 고쳐줘. |
| nimble | exp-026 | L2 | L1→L2 | 개선 | 학습 루프에 --max-grad-norm 옵션으로 gradient clipping 추가해줘. |
| nimble | exp-029 | L2 | L3→L2 | 개선 | Rename the CLI option `--retries` to `--max-retries` in the command, its help text and the docs, keeping the old name as a hidden alias. |
| nimble | exp-037 | L4 | L4→L5 | 악화 | A flaky test turned out to be a real race: two workers sometimes both acquire the same lease and double-process a job. Find the root cause and fix it. |
| nimble | exp-039 | L3 | L3→L1 | 악화 | 장바구니랑 위시리스트 상태를 Redux에서 Zustand로 바꿔줘. 컴포넌트 여러 개 걸려 있어. |
| nimble | exp-047 | L3 | L1→L3 | 개선 | Terraform에 ALB + ASG 모듈 추가하고 기존 ec2 스택이 그걸 참조하게 바꿔줘. |
| nimble | exp-057 | L4 | L3→L4 | 개선 | 프로세스 메모리에 두던 세션을 Redis로 옮기는 diff야. 로그인/로그아웃/만료 흐름까지 포함돼 있어. 리뷰만 해줘, 수정하지 마. |
| nimble | exp-068 | L2 | L1→L2 | 개선 | Replace the ~40 logger.info(...) calls with the new log_event() helper, keeping the same fields as today. |
| nimble | exp-069 | L5 | L3→L5 | 개선 | 부하 걸릴 때만 가끔 주문이 두 번 결제돼. 로그엔 같은 payment_intent로 요청이 2번 찍혀. 원인 찾고 고쳐줘. |
| nimble | exp-070 | L1 | L1→L3 | 악화 | Review only: look over my typo-fix PR in docs/ and tell me if anything is off. Don't edit. |
| nimble | exp-074 | L4 | L3→L4 | 개선 | 모놀리식 Express 앱을 users, orders, catalog 모듈로 나누고 의존 방향 정리해줘. |
| nimble | exp-076 | L5 | L3→L5 | 개선 | Rewrite JWT signing to support key rotation with kid, an overlap window and revocation, keeping old tokens valid until expiry. Check this diff, don't change anything. |
| nimble | exp-079 | L4 | L3→L4 | 개선 | 공개 SDK 인증을 API key에서 OAuth2 client credentials로 바꾸고, 기존 key도 6개월은 지원해야 해. |
| nimble | exp-087 | L3 | L3→L1 | 악화 | Move our CI from Jenkins to GitHub Actions: build, test, deploy stages with environment secrets and approval gates. |
| nimble | exp-107 | L4 | L3→L4 | 개선 | 결제 모듈에 PG사 추상화 계층을 만들고 현재 단일 PG 연동을 어댑터로 옮겨줘. |
| nimble | exp-110 | L3 | L2→L3 | 개선 | 프로젝트 하위 라우트 전체에 admin/editor/viewer 역할별 접근 제어를 적용하는 계획만 세워줘. 구현은 하지 마. |

## 재현용 자료

- 기존 질문 결과: `runs/compare-v1-live-20261004.json` / `.md`.
- 보강 질문 결과: `runs/compare-v1-live-guide-20261004.json` / `.md`.
- 정확한 보강 level 질문: `runs/live-guide-level-question-20261004.json`.
- 보강 Jev 응답 모델: `jev-1.13.0` (150 responses), Nimble 응답 모델: `nimble` (150 responses), 각 `runs/live-guide-*-metadata-20261004.json`에 기록. 기존 CLI 결과는 응답 모델 버전을 별도 보존하지 않으며 각 backend의 동일 기본 모델 설정을 사용했다.
- 실험 구현은 transport wrapper에서 request를 새 dict로 복사해 level 질문만 교체했다. 실제 소스의 `QUESTIONS`는 변경하지 않았고, 나머지 질문이 동일하다는 assert를 300회 확인했다.
- 결과별 case ID 150건 완전 일치, scored 130건, fallback 0, exact+over+under=130 및 보강 transport 호출 수 각각 150을 assert로 검증했다.

제품 설정을 바꾸거나 새 threshold를 채택하지 않았다. 다음 단계는 분류 질문 보강의 holdout 검증과 Nimble L3·중대 과소 회귀를 줄이는 실험이다.

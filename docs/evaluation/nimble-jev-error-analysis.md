# Jev / Nimble: 정확도 80% 미만 레벨 원인 분석

분석일: 2026-10-04. 코드 변경 및 새 live 모델 호출 없이 저장된 응답을 현재 backend의 실제 파서·보정 규칙에 재입력했다. 전체 150건 × backend 2개를 재생했고, 원래 표의 80% 미만 6개 레벨에 속한 오분류 **45건**을 전수 확인했다. 서로 겹치는 case가 있으므로 45는 backend별 예측 오류 수다.

입력 기록: `runs/compare-v1-jev-dist.json`, `runs/compare-v1-nimble2.json`. 정답: `evaluation/corpus/corpus-v1.jsonl`. 모델의 내부 추론이나 원 응답 전체는 기록되지 않았으므로 문장 해석에 관한 설명은 가설로 구분한다.

## 결과

| Backend | 레벨 | 저장된 정확도 | 현재 코드 재생 정확도 | 주요 관찰 |
|---|---|---:|---:|---|
| jev | L2 | 24/32 (75.0%) | 24/32 (75.0%) | L3로 과대 7건, L1로 과소 1건. 모두 원 모델 argmax 오류; L4 보정과 무관. |
| jev | L3 | 24/34 (70.6%) | 30/34 (88.2%) | L4 과대 8건·L5 과대 2건 중 6건을 기존 보정이 이미 해결. 남은 4건은 기능 추가와 고위험 구조 변경 혼동. |
| jev | L5 | 11/15 (73.3%) | 11/15 (73.3%) | L4 과소 3건, L3 과소 1건. 현재 보정으로 내려간 사례는 없음. |
| nimble | L2 | 23/32 (71.9%) | 23/32 (71.9%) | L1 과소 5건, L3 과대 4건. 모두 원 argmax 오류; 승격 규칙과 무관. |
| nimble | L4 | 16/23 (69.6%) | 16/23 (69.6%) | L3 과소 6건, L5 과대 1건. 구조·저장·통신 계약 변경을 L3로 평가. |
| nimble | L5 | 8/15 (53.3%) | 8/15 (53.3%) | L4 과소 4건, L3 과소 3건. 위험 플래그는 오분류 7건 모두 정답 플래그를 포함. |

Jev 전체는 현재 코드 재생에서 113/130(86.9%), Nimble은 101/130(77.7%). 이전 82.3% Jev 수치는 L4 강등 보정 전 보고서다. 이는 새 live 정확도가 아니라 동일 모델 확률을 현재 규칙에 넣은 결과다.

## 확인된 원인과 가설

- **확인: 모델 점수 단계에서 난이도 경계를 틀린다.** Nimble L5 15건의 raw argmax는 L5 7 / L4 2 / L3 5 / L2 1이다. 승격 보정으로 L5 정답은 7→8건이며 오답 L3 두 건도 L4로 올라가 피해가 줄었다. 보정이 기존 L5를 낮추는 문제는 아니다.
- **확인: 위험 인식과 난이도 인식이 별도다.** Nimble L5 오분류 7건 전부 정답 risk_flags를 탐지했다. 위험 임계값을 낮추는 것으로 이 7건의 level을 고칠 수 없다. `session_plan`은 위험만으로 시작 프로필을 높이지 않으며, `classify_with_fallback`은 실패·잘못된 응답에만 다음 backend를 호출한다. 정상 응답의 저신뢰 판정에는 fallback이 없다.
- **확인: 분류기에 라벨링 경계 규칙을 충분히 주지 않는다.** `QUESTIONS["level"]`은 다섯 개의 짧은 `LEVEL_DESCRIPTIONS`만 사용한다. labeling-guide의 (1) 파일 수보다 판단량, (8) plan/review는 구현했을 때 난이도, (12~13) migration/보안 핵심 앵커는 전달되지 않는다. 이것이 얼마나 개선되는지는 동일 조건 live A/B가 필요하다.
- **확인: 라벨 경계 자체가 애매한 사례가 있다.** Jev L2 오답 8건 중 seed-016, exp-014, exp-064는 독립 라벨도 L2/L3 불일치였다. 그러나 모델이 틀린 나머지 사례까지 라벨 오류라고 볼 근거는 없다. 전체 라벨은 AI 합의이고 사람 검증은 없다.
- **가설: 짧은 요청의 표면적 수정 규모를 우선한다.** logger 교체·Compose·CI·gradient clipping에서는 동일 작업을 Jev가 L3, Nimble이 L1로 보는 사례가 있다. 복합 결제 장애도 구체적 단서가 있으면 국소 수정처럼 볼 가능성이 있다. 내부 reasoning이 없어 확정할 수 없다.
- **미확인: review/plan 문구가 난이도를 낮추는 효과.** exp-076 JWT 리뷰, exp-057 세션 이전 리뷰 등에서 보인다. 그러나 동일 작업의 문구만 바꾼 쌍이 아니므로 인과는 검증되지 않았다.
- **배제 가능한 경로:** 기록상 fallback_count는 둘 다 0. 최대 task 길이는 166자로 4000자 제한에 걸리지 않는다. Nimble 저장 예측은 현재 기본 규칙으로 150/150 재현됐다. 응답 파싱/기본 fallback/입력 잘림이 이 기록의 낮은 점수를 설명하지 않는다.

## Nimble 승격 임계값 민감도 — 동일 저장 응답 재생

| P(L4)+P(L5) 승격 기준 | 전체 exact | L3 exact | L4 exact | L5 exact | 과대 / 과소 |
|---|---:|---:|---:|---:|---:|
| 비활성 | 94/130 | 30/34 | 10/23 | 7/15 | 6 / 30 |
| 0.2 | 101/130 | 30/34 | 16/23 | 8/15 | 8 / 21 |
| 0.18 | 102/130 | 30/34 | 17/23 | 8/15 | 8 / 20 |
| 0.15 | 102/130 | 29/34 | 18/23 | 8/15 | 9 / 19 |
| 0.1 | 101/130 | 27/34 | 18/23 | 9/15 | 11 / 18 |
| 0.05 | 102/130 | 24/34 | 21/23 | 10/15 | 14 / 14 |

임계값 0.05로 낮춰도 L5는 10/15(66.7%)에 그치고 L3는 30/34→24/34로 하락한다. P(L4)>P(L5)인 L4 argmax를 L5로 옮기는 기능은 이 승격 규칙에 없다. 기존 0.2를 임의로 낮추는 단일 조정으로 모든 레벨 80%를 달성하지 못한다. 이 표본으로 임계값을 고르면 과적합이며 holdout 검증이 필요하다.

## 오분류 45건 전수 목록

아래 해석은 요청 문장·정답 가이드·확률 및 실제 보정 분기 비교에 기반한다. 모델 내부 추론을 재구성한 것은 아니다.

| Backend | ID | 정답 | 저장→현재 | raw argmax | P(L4)+P(L5) | 요청 | 분석 |
|---|---|---|---|---|---:|---|---|
| jev | exp-014 | L2 | L3→L3 | L3 | 0.240 | Review this profile image upload code (type sniffing, 5MB cap, S3 storage) for problems. Don't change anything. | 업로드 검토의 경계 사례. 독립 라벨 L2/L3 불일치이며 모델에는 검토 대상 코드가 제공되지 않음. |
| jev | exp-019 | L2 | L3→L3 | L3 | 0.020 | 개발용 Docker Compose에 Postgres, Redis, 마이그레이션 컨테이너 추가하고 헬스체크 기준으로 기동 순서 맞춰줘. | 개발용 Compose 구성과 기동 순서 변경. Jev는 L3, Nimble은 L1로 양쪽 경계 오판. migration container를 migration 작업으로 오탐. |
| jev | exp-026 | L2 | L3→L3 | L3 | 0.000 | 학습 루프에 --max-grad-norm 옵션으로 gradient clipping 추가해줘. | 기존 학습 루프의 국소 gradient clipping 추가. Jev L3, Nimble L1로 양쪽 경계 오판. |
| jev | exp-029 | L2 | L3→L3 | L3 | 0.000 | Rename the CLI option `--retries` to `--max-retries` in the command, its help text and the docs, keeping the old name as a hidden alias. | CLI 이름 교체에 옛 이름 호환 alias 유지가 포함됨. 여러 문서·호출부를 바꾸는 범위를 L3로 과대 평가. |
| jev | exp-064 | L2 | L3→L3 | L3 | 0.000 | Set up a GitHub Actions matrix for Python 3.10-3.12 with a shared cached venv and a separate lint job, and make release.yml depend on both. | CI matrix·lint 의존성 구성. 독립 라벨 L2/L3 불일치. Jev L3, Nimble L1로 양쪽 경계 오판. |
| jev | exp-068 | L2 | L3→L3 | L3 | 0.000 | Replace the ~40 logger.info(...) calls with the new log_event() helper, keeping the same fields as today. | 동일 필드를 유지하는 40개 logger 호출 교체. 파일·호출 수보다 코드 이해 및 계약 유지 판단량을 평가해야 함. |
| jev | exp-092 | L2 | L1→L1 | L1 | 0.000 | GitHub Actions에 pip 캐시 단계 넣어서 CI 시간 줄여줘. | pip 캐시 단계 추가를 기계적 config L1로 평가. 코퍼스의 국소 CI 변경 L2와 경계 차이. |
| jev | seed-016 | L2 | L3→L3 | L3 | 0.010 | Replace the ad-hoc logging calls in the worker modules with the structured logger and keep the log fields stable | 기존 로그 필드 유지라는 기계적 대응을 여러 worker 모듈 변경보다 우선해야 하는 경계. 독립 라벨도 L2/L3 불일치. |
| jev | exp-006 | L3 | L4→L3 | L4 | 0.680 | Add per-API-key rate limiting with a token bucket in Redis, applied across the gateway routes. | 기존 gateway에 Redis rate limiter 추가를 동시성 구조 변경으로 과대 평가. 현재 Jev concurrency 보정으로 L3 복구. |
| jev | exp-008 | L3 | L4→L3 | L4 | 0.510 | Check this diff that adds idempotency keys to POST /payments so retries can't double charge. Review only, no edits. | 멱등성 기능 추가와 복합 장애의 원인 분석을 구별해야 함. 현재 Jev concurrency 보정으로 L3 복구. |
| jev | exp-012 | L3 | L4→L3 | L4 | 0.710 | Add a nightly worker that emails digests via the queue. Two workers must never send the same digest. | 기존 queue의 digest worker 추가를 L4로 평가. 현재 Jev concurrency 보정으로 L3 복구. |
| jev | exp-041 | L3 | L4→L3 | L4 | 0.750 | Convert the iOS app's networking layer from completion handlers to async/await across all 9 service classes, with proper cancellation. | async/await 전환을 구조 재설계로 과대 평가. 현재 Jev concurrency 보정으로 L3 복구. |
| jev | exp-056 | L3 | L5→L5 | L5 | 0.750 | GDPR 삭제 요청이 오면 연관 테이블 5곳에서 개인정보를 익명화하거나 삭제하는 배치 작업을 추가해줘. | 기존 구조의 개인정보 삭제 배치와 복구 불가능한 데이터 손실 migration의 경계. 의도된 삭제를 L5 난이도로 과대 평가. |
| jev | exp-089 | L3 | L4→L3 | L4 | 0.560 | 프로젝트 soft delete 도입: deleted_at 컬럼, 모든 조회에서 필터링, 복구 엔드포인트까지. | 호환 가능한 soft-delete 기능 추가와 저장 구조 재설계의 경계. 현재 Jev 고난도 확률 보정으로 L3 복구. |
| jev | exp-102 | L3 | L4→L3 | L4 | 0.500 | 푸시 알림 설정 화면을 iOS, Android 앱에 추가하고 서버에 /me/notification-prefs API도 만들어줘. | 모바일·서버 여러 계층 기능 추가를 L4 구조 변경으로 과대 평가. 현재 Jev 보정으로 L3 복구. |
| jev | exp-110 | L3 | L4→L4 | L4 | 0.680 | 프로젝트 하위 라우트 전체에 admin/editor/viewer 역할별 접근 제어를 적용하는 계획만 세워줘. 구현은 하지 마. | 기존 라우트의 역할별 접근 제어 추가를 L4로 과대 평가. 위험 플래그 auth와 구조 변경의 구별 부족. |
| jev | seed-034 | L3 | L4→L4 | L4 | 0.750 | Draft a plan for adding OAuth login to the web app, then wait for my approval | 기존 앱에 OAuth 기능을 추가하는 L3와 인증 구조 재설계 L4의 경계. 위험 신호와 구조 변경을 구별해야 함. |
| jev | seed-036 | L3 | L5→L5 | L5 | 0.630 | 리뷰만 해줘. 방금 바꾼 결제 모듈 코드에 문제가 없는지 검토해줘 | 결제 모듈 검토를 L5로 과대 평가. 실제 코드 없이 보안 핵심 재작성·복합 장애를 추정할 근거가 부족함. |
| jev | exp-004 | L5 | L4→L4 | L4 | 0.970 | The partner payout job sometimes sends payouts twice after a crash mid-batch. Make it crash-safe and reconcile what already went out. | 크래시 후 이중 지급 복구·정산을 L5 검증 문제보다 L4 설계로 판단. 두 backend 모두 실패; Nimble P(L5)=0.007. |
| jev | exp-042 | L5 | L4→L4 | L4 | 0.850 | 동시 주문이 몰릴 때만 재고가 가끔 음수가 돼. 재현이 잘 안 돼. 원인 찾아서 고쳐줘. | 재현 어려운 재고 동시성 장애의 L5를 Jev L4로 판단. P(L4)=0.44/P(L5)=0.41로 근접한 경계. |
| jev | exp-069 | L5 | L3→L3 | L3 | 0.530 | 부하 걸릴 때만 가끔 주문이 두 번 결제돼. 로그엔 같은 payment_intent로 요청이 2번 찍혀. 원인 찾고 고쳐줘. | 부하 때만 발생하는 이중 결제 원인 분석을 두 backend 모두 L3로 평가. 위험은 탐지했지만 구체적 payment_intent 단서를 국소 수정으로 해석했을 가능성(가설). |
| jev | exp-090 | L5 | L4→L4 | L4 | 0.980 | Plan the change of orders primary key from integer id to UUID, including 6 dependent foreign keys and an online backfill. Draft the plan and wait. | PK UUID 전환·6개 FK·온라인 backfill을 L4 설계로 평가. 두 backend 모두 실패. 무손실 검증 앵커를 prompt에 명시할 필요. |
| nimble | exp-014 | L2 | L3→L3 | L3 | 0.006 | Review this profile image upload code (type sniffing, 5MB cap, S3 storage) for problems. Don't change anything. | 업로드 검토의 경계 사례. 독립 라벨 L2/L3 불일치이며 모델에는 검토 대상 코드가 제공되지 않음. |
| nimble | exp-019 | L2 | L1→L1 | L1 | 0.011 | 개발용 Docker Compose에 Postgres, Redis, 마이그레이션 컨테이너 추가하고 헬스체크 기준으로 기동 순서 맞춰줘. | 개발용 Compose 구성과 기동 순서 변경. Jev는 L3, Nimble은 L1로 양쪽 경계 오판. migration container를 migration 작업으로 오탐. |
| nimble | exp-026 | L2 | L1→L1 | L1 | 0.002 | 학습 루프에 --max-grad-norm 옵션으로 gradient clipping 추가해줘. | 기존 학습 루프의 국소 gradient clipping 추가. Jev L3, Nimble L1로 양쪽 경계 오판. |
| nimble | exp-029 | L2 | L3→L3 | L3 | 0.001 | Rename the CLI option `--retries` to `--max-retries` in the command, its help text and the docs, keeping the old name as a hidden alias. | CLI 이름 교체에 옛 이름 호환 alias 유지가 포함됨. 여러 문서·호출부를 바꾸는 범위를 L3로 과대 평가. |
| nimble | exp-062 | L2 | L3→L3 | L3 | 0.006 | Check reports/monthly.sql: customers with no refunds seem to vanish. Review only, tell me what's wrong and don't edit. | 단일 SQL의 누락 행 원인 검토를 L3로 평가. 실제 SQL은 제공되지 않아 JOIN/filter 수정 범위를 확정할 수 없음. |
| nimble | exp-064 | L2 | L1→L1 | L1 | 0.004 | Set up a GitHub Actions matrix for Python 3.10-3.12 with a shared cached venv and a separate lint job, and make release.yml depend on both. | CI matrix·lint 의존성 구성. 독립 라벨 L2/L3 불일치. Jev L3, Nimble L1로 양쪽 경계 오판. |
| nimble | exp-068 | L2 | L1→L1 | L1 | 0.003 | Replace the ~40 logger.info(...) calls with the new log_event() helper, keeping the same fields as today. | 동일 필드를 유지하는 40개 logger 호출 교체. 파일·호출 수보다 코드 이해 및 계약 유지 판단량을 평가해야 함. |
| nimble | exp-092 | L2 | L1→L1 | L1 | 0.003 | GitHub Actions에 pip 캐시 단계 넣어서 CI 시간 줄여줘. | pip 캐시 단계 추가를 기계적 config L1로 평가. 코퍼스의 국소 CI 변경 L2와 경계 차이. |
| nimble | seed-016 | L2 | L3→L3 | L3 | 0.005 | Replace the ad-hoc logging calls in the worker modules with the structured logger and keep the log fields stable | 기존 로그 필드 유지라는 기계적 대응을 여러 worker 모듈 변경보다 우선해야 하는 경계. 독립 라벨도 L2/L3 불일치. |
| nimble | exp-035 | L4 | L3→L3 | L3 | 0.030 | DB 읽기 replica를 도입하고 조회 쿼리는 replica로 보내도록 데이터 접근 계층을 바꿔줘. | DB read replica와 데이터 접근 경로 변경을 L3로 평가. Nimble 고난도 확률 질량 0.030. |
| nimble | exp-057 | L4 | L3→L3 | L3 | 0.176 | 프로세스 메모리에 두던 세션을 Redis로 옮기는 diff야. 로그인/로그아웃/만료 흐름까지 포함돼 있어. 리뷰만 해줘, 수정하지 마. | 메모리 세션을 Redis로 이전하는 구조 변경을 L3로 평가. 리뷰 요청은 구현했을 때 난이도로 평가한다는 지침이 prompt에 없음. |
| nimble | exp-074 | L4 | L3→L3 | L3 | 0.181 | 모놀리식 Express 앱을 users, orders, catalog 모듈로 나누고 의존 방향 정리해줘. | 모놀리식 앱 분리를 L3로 평가. Nimble 고난도 확률 0.181로 승격 기준 0.2 직전; target도 route 대신 plan_only 오판. |
| nimble | exp-079 | L4 | L3→L3 | L3 | 0.090 | 공개 SDK 인증을 API key에서 OAuth2 client credentials로 바꾸고, 기존 key도 6개월은 지원해야 해. | 공개 SDK 인증 계약 변경과 6개월 구버전 호환을 L3로 평가. 고난도 확률 0.090. |
| nimble | exp-107 | L4 | L3→L3 | L3 | 0.069 | 결제 모듈에 PG사 추상화 계층을 만들고 현재 단일 PG 연동을 어댑터로 옮겨줘. | PG사 추상화 계층 도입과 기존 연동의 adapter 이전을 L3 기능 추가로 평가. 고난도 확률 0.069. |
| nimble | seed-024 | L4 | L3→L3 | L3 | 0.057 | Introduce an event bus between the order and notification services and migrate direct calls to events | 서비스 간 직접 호출을 event bus로 바꾸는 통신 방식 변경을 L3 기능 추가로 평가. Nimble 고난도 확률 질량 0.057. |
| nimble | seed-026 | L4 | L5→L5 | L2 | 0.284 | Migrate the orders table to a new schema with a changed primary key; write the migration and backfill | 키 변경/backfill의 L4를 L5로 승격. 데이터 손실 위험을 잡았지만 L4/L5 난이도 분리 실패; 기존 argmax는 L2. |
| nimble | exp-004 | L5 | L4→L4 | L3 | 0.314 | The partner payout job sometimes sends payouts twice after a crash mid-batch. Make it crash-safe and reconcile what already went out. | 크래시 후 이중 지급 복구·정산을 L5 검증 문제보다 L4 설계로 판단. 두 backend 모두 실패; Nimble P(L5)=0.007. |
| nimble | exp-043 | L5 | L4→L4 | L4 | 0.796 | Redesign the event-sourcing store so snapshots and replay stay consistent across a schema upgrade, without losing any events. | schema upgrade 중 snapshot/replay 일관성과 이벤트 무손실 요구를 Nimble L4로 평가. P(L4)=0.539>P(L5)=0.258. |
| nimble | exp-069 | L5 | L3→L3 | L3 | 0.104 | 부하 걸릴 때만 가끔 주문이 두 번 결제돼. 로그엔 같은 payment_intent로 요청이 2번 찍혀. 원인 찾고 고쳐줘. | 부하 때만 발생하는 이중 결제 원인 분석을 두 backend 모두 L3로 평가. 위험은 탐지했지만 구체적 payment_intent 단서를 국소 수정으로 해석했을 가능성(가설). |
| nimble | exp-076 | L5 | L3→L3 | L3 | 0.098 | Rewrite JWT signing to support key rotation with kid, an overlap window and revocation, keeping old tokens valid until expiry. Check this diff, don't change anything. | JWT 키 회전·겹침 기간·폐기의 핵심 보안 구현을 Nimble L3 검토로 평가. 구현 난이도 기준 prompt 미명시가 영향을 줄 가능성(미검증). |
| nimble | exp-090 | L5 | L4→L4 | L4 | 0.509 | Plan the change of orders primary key from integer id to UUID, including 6 dependent foreign keys and an online backfill. Draft the plan and wait. | PK UUID 전환·6개 FK·온라인 backfill을 L4 설계로 평가. 두 backend 모두 실패. 무손실 검증 앵커를 prompt에 명시할 필요. |
| nimble | seed-027 | L5 | L4→L4 | L3 | 0.325 | Rewrite the authentication token signing and verification to rotate keys without invalidating live sessions | 토큰 서명·검증 키 회전을 L5 보안 핵심으로 평가하지 못함. Nimble은 raw L3→L4 승격되지만 P(L4)>P(L5). |
| nimble | seed-028 | L5 | L3→L3 | L3 | 0.068 | Intermittent double charges appear under load; find the root cause across the payment, queue and retry code and fix it | 부하에서만 발생하는 복합 이중 결제 원인 분석을 Nimble L3로 평가. payment/concurrency는 탐지했지만 고난도 확률 0.068. |

## 다음 검증 우선순위

1. level 질문에 기존 라벨 가이드의 경계·앵커만 반영해 A/B 평가. 특히 L1/L2/L3 판단량, L4/L5 원인 불명·무손실 검증, plan/review 구현 난이도 기준.
2. 같은 작업의 plan/review/implement 문구를 짝지어 target과 난이도의 분리 여부 검증.
3. 별도 사람 라벨 holdout에서 Jev/Nimble을 같은 조건으로 재평가. 임계값 조정은 그 이후.
4. Nimble의 정상 응답이지만 불확실한 고위험 요청을 Jev로 재확인하는 정책은 정확도·호출률·비용을 함께 측정한 뒤 결정. 현재 error-only fallback을 바꾸는 별도 동작이다.

이번 조사에서 코드·임계값·라벨은 변경하지 않았다.

## 후속 live 검증

2026-10-04 동일 코퍼스로 기존/보강 질문 총 600회 live 비교를 완료했다. 두 backend 모두 보강 후 L5 13/15지만 Nimble L3 및 중대 과소 지표는 악화됐다. 자세한 최신 수치와 부작용은 [live 비교 보고서](live-router-comparison-20261004.md)를 참고한다.

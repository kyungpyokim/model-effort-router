# corpus-v2 300개 live 비교 — 2026-10-04

300건 × backend 2종 × level 질문 2종 = **1,200회 새 live 호출**. 레벨 평가는 조건마다 250건, target 평가는 300건. HTTP 200 1,200건, 전송 오류 0건, fallback 0건. 저장된 v1 결과를 이번 점수에 재사용하지 않았다.

기존 질문은 제품의 QUESTIONS, 보강 질문은 이전 실험의 `runs/live-guide-level-question-20261004.json`을 그대로 사용했다. transport wrapper에서 level 질문만 교체하고 나머지 질문이 같다는 assert를 호출마다 확인했다. 모델 설정·임계값·제품 코드는 변경하지 않았다. Jev와 Nimble은 병렬 실행했으며 각 backend 안에서는 기존→보강 순서로 호출했다. Nimble의 두 조건은 동시에 실행하지 않았다.

## 레벨별 정확도

| 정답 레벨 | n | Jev 기존 | Jev 보강 | Nimble 기존 | Nimble 보강 |
|---|---:|---:|---:|---:|---:|
| L1 | 51 | 49/51 (96.1%) | 49/51 (96.1%) | 45/51 (88.2%) | 48/51 (94.1%) |
| L2 | 49 | 41/49 (83.7%) | 46/49 (93.9%) | 38/49 (77.6%) | 38/49 (77.6%) |
| L3 | 50 | 46/50 (92.0%) | 49/50 (98.0%) | 44/50 (88.0%) | 42/50 (84.0%) |
| L4 | 50 | 50/50 (100.0%) | 45/50 (90.0%) | 39/50 (78.0%) | 45/50 (90.0%) |
| L5 | 50 | 44/50 (88.0%) | 48/50 (96.0%) | 34/50 (68.0%) | 47/50 (94.0%) |
| 전체 | 250 | 230/250 (92.0%) | 237/250 (94.8%) | 200/250 (80.0%) | 220/250 (88.0%) |

## 기존/추가분 분리

v1은 질문·임계값 조정에 쓰인 사례다. 추가분은 가이드에 따라 생성하고 두 Codex 에이전트가 독립 라벨링한 합성 사례이며, 사람의 라벨 검증과 실제 사용자 분포 검증은 아직 없다. 새 사례는 이번 실험 전에 Jev/Nimble 예측을 보고 라벨링하지 않았다. 전체 300건을 독립 holdout으로 부르지 않는다.

| 범위 | 레벨 n | Jev 기존 | Jev 보강 | Nimble 기존 | Nimble 보강 |
|---|---:|---:|---:|---:|---:|
| 합본 | 250 | 230/250 (92.0%) | 237/250 (94.8%) | 200/250 (80.0%) | 220/250 (88.0%) |
| 기존 v1 | 130 | 113/130 (86.9%) | 123/130 (94.6%) | 101/130 (77.7%) | 111/130 (85.4%) |
| 새 150개 | 120 | 117/120 (97.5%) | 114/120 (95.0%) | 99/120 (82.5%) | 109/120 (90.8%) |

## 운용 지표

| 조건 | target 정확도 | 과대/과소 | critical miss | p50 ms | merged risk recall / precision | tokens in/out |
|---|---:|---:|---:|---:|---:|---:|
| jev baseline | 294/300 (98.0%) | 13/7 | 0/128 | 243 | 149/158 (94.3%) / 149/238 (62.6%) | 218344/49307 |
| jev guide | 294/300 (98.0%) | 4/9 | 1/128 | 247 | 150/158 (94.9%) / 150/245 (61.2%) | 320644/49307 |
| nimble baseline | 289/300 (96.3%) | 14/36 | 2/128 | 984 | 144/158 (91.1%) / 144/237 (60.8%) | 1813588/2700 |
| nimble guide | 289/300 (96.3%) | 12/18 | 6/128 | 1245 | 141/158 (89.2%) / 141/226 (62.4%) | 2603188/2700 |

critical miss는 평가 도구의 정의다: 정답 L4/L5 또는 위험 플래그가 있는 사례에서 정답보다 낮고 L2 이하로 판정. 이 집계에는 L2 보안 작업을 L1로 판단한 경우도 포함되므로 모든 사례가 같은 심각도라는 뜻은 아니다.

## 결과 해석

- Jev: 합본 92.0%→94.8%지만 새 사례는 97.5%→95.0%, L4는 100%→90%. 전체 정확도 개선만으로 보강 질문을 전면 채택할 근거는 부족하다. 기존 질문의 L2/L5 오답은 보강으로 줄었으나 일부 구조 변경을 L3로 낮게 보았다.
- Nimble: 합본 80.0%→88.0%, 새 사례 82.5%→90.8%. L5는 68%→94%, L4는 78%→90%로 개선됐다. L2는 두 조건 모두 38/49(77.6%). 동일 정답 수라도 개선/회귀 사례가 서로 상쇄된 결과다.
- Nimble L3: 합본 88%→84%, 기존 150개 부분은 30/34→27/34, 새 부분은 14/16→15/16. 이전 L3 하락은 기존 부분에서 재현됐지만 새 부분에서는 개선되어 전체 L3의 일반적 성능 저하로 단정하기 어렵다.
- Nimble의 critical miss는 2→6건으로 증가했다. 평균 정확도와 깊은 과소 판정을 함께 봐야 한다. 보강 질문 또는 임계값은 제품 설정에 채택하지 않았다.
- 모델의 내부 추론은 측정하지 않았다. 아래 raw argmax와 최종 레벨의 차이는 실제 분포 및 현재 후처리 규칙으로 확인 가능한 사실이고, 특정 문장이나 키워드가 원인이라는 해석은 별도 ablation 없이는 가설이다.

## Nimble 잔여 오답의 분해

2026-10-04 후속 분석은 위 live 결과의 확률을 읽어 수행했다. 새 live 호출이나 제품 설정 변경은 없다.

- **제품 질문은 기존 질문이다.** 보강 질문은 transport wrapper 실험에만 사용했다. 실제 기본값 기준 합본 L2 77.6%, L4 78.0%, L5 68.0%가 남아 있다. 보강 조건에서는 합본 기준 L2만 80% 미만이며, 부분집합에서는 기존 L3도 79.4%다.
- **L2 오류는 승격 임계값의 문제가 아니다.** 두 질문 모두 L2 오답 11개는 raw argmax와 최종 레벨이 같다. L1로 낮게 본 6개, L3로 높게 본 5개다. 보강 질문은 기존 오답 5개(seed-016, exp-026, exp-029, exp-068, add-036)를 고쳤지만 정답 5개(seed-035, exp-018, add-034, add-035, add-041)를 새로 틀려 38/49 그대로다. 이는 현 질문에서 국소 판단이 필요한 변경과 기계적 변경/다계층 변경의 경계 판정이 일관되지 않다는 관측이다.
- **L2 리뷰 요청이 특히 흔들린다.** 정답 target이 review_only인 L2 7개는 4/7→2/7로 하락했다. route L2는 32/40→34/40로 개선, plan_only는 2/2→2/2다. 단순 환불 SDK 인자 교체(add-034)는 L2 확률 0.567→0.374, L3 0.324→0.499로 바뀌었다. 로그의 비밀번호 제거(add-041)는 L2 0.584→0.421, L1 0.371→0.540으로 바뀌었다. 어떤 문장 또는 결제·보안 키워드가 원인인지는 ablation 없이는 확정하지 않는다.
- **고정 승격 규칙은 일부 회귀를 증폭한다.** 보강 exp-012는 raw L3가 여전히 0.439로 최댓값인데 L4+L5=0.2054가 기존 0.2 임계값을 넘어 최종 L4가 됐다. seed-036은 raw L2가 0.387로 L5 0.376보다 높지만 L4+L5=0.3836 때문에 최종 L5로 올라갔다. 후자는 raw도 오답이므로 승격이 새로운 오답을 만들었다고 세지 않는다.
- **승격을 끄는 것만으로 해결되지 않는다.** 저장 분포의 raw argmax 정확도는 기존 185/250→최종 200/250, 보강 215/250→최종 220/250다. 기존 승격은 정답으로 고친 16개·새 오답 1개, 보강에서는 정답으로 고친 6개·새 오답 1개다. 승격은 순효과가 양수이며 L2 오답 11개에는 영향을 주지 않는다.
- **표의 낮은 구간들은 독립적인 오답 집합이 아니다.** 합본/기존/새 부분에 같은 오답이 중복 포함된다. 코퍼스는 합성 AI 라벨이며, 특히 한 단계 경계의 판단은 사람 검증이 필요하다. 분류기는 task와 paths만 받으므로 요청에서 언급한 실제 diff나 코드 내용은 이 실험에 제공하지 않았다.

다음 수정의 우선순위는 L2 경계를 짧고 구체적으로 분리한 질문의 ablation, review_only 구현 범위 해석 검증, 변경된 질문에 맞는 확률 보정이다. 전체 정확도와 깊은 과소 판정을 함께 검증해야 하며 기존 결과를 보면서 조정한 뒤 같은 결과를 독립 검증이라고 부르지 않는다.

## 80% 미만 구간과 모든 오답

합본뿐 아니라 기존/새 부분의 레벨별 정확도도 확인했다. 아래 구간은 정확도가 엄격히 80% 미만인 경우다. 이후 표는 해당 구간에 속하는 모든 오답을 조건별로 한 번씩 표시한다.

| backend | 질문 | 범위 | 레벨 | 정확도 |
|---|---|---|---|---:|
| jev | baseline | 기존 v1 | L2 | 24/32 (75.0%) |
| jev | baseline | 기존 v1 | L5 | 11/15 (73.3%) |
| nimble | baseline | 합본 | L2 | 38/49 (77.6%) |
| nimble | baseline | 합본 | L4 | 39/50 (78.0%) |
| nimble | baseline | 합본 | L5 | 34/50 (68.0%) |
| nimble | baseline | 기존 v1 | L2 | 23/32 (71.9%) |
| nimble | baseline | 기존 v1 | L4 | 16/23 (69.6%) |
| nimble | baseline | 기존 v1 | L5 | 8/15 (53.3%) |
| nimble | baseline | 새 150개 | L5 | 26/35 (74.3%) |
| nimble | guide | 합본 | L2 | 38/49 (77.6%) |
| nimble | guide | 기존 v1 | L2 | 25/32 (78.1%) |
| nimble | guide | 기존 v1 | L3 | 27/34 (79.4%) |
| nimble | guide | 새 150개 | L2 | 13/17 (76.5%) |

| backend | 질문 | ID | 해당 범위 | 정답→예측 | raw argmax | P(L4)+P(L5) | 요청 |
|---|---|---|---|---|---|---:|---|
| jev | baseline | seed-016 | 기존 v1 | L2→L3 | L3 | 0.010 | Replace the ad-hoc logging calls in the worker modules with the structured logger and keep the log fields stable |
| jev | baseline | exp-004 | 기존 v1 | L5→L4 | L4 | 0.960 | The partner payout job sometimes sends payouts twice after a crash mid-batch. Make it crash-safe and reconcile what already went out. |
| jev | baseline | exp-014 | 기존 v1 | L2→L3 | L3 | 0.230 | Review this profile image upload code (type sniffing, 5MB cap, S3 storage) for problems. Don't change anything. |
| jev | baseline | exp-019 | 기존 v1 | L2→L3 | L3 | 0.020 | 개발용 Docker Compose에 Postgres, Redis, 마이그레이션 컨테이너 추가하고 헬스체크 기준으로 기동 순서 맞춰줘. |
| jev | baseline | exp-026 | 기존 v1 | L2→L3 | L3 | 0.000 | 학습 루프에 --max-grad-norm 옵션으로 gradient clipping 추가해줘. |
| jev | baseline | exp-029 | 기존 v1 | L2→L3 | L3 | 0.000 | Rename the CLI option `--retries` to `--max-retries` in the command, its help text and the docs, keeping the old name as a hidden alias. |
| jev | baseline | exp-042 | 기존 v1 | L5→L4 | L4 | 0.860 | 동시 주문이 몰릴 때만 재고가 가끔 음수가 돼. 재현이 잘 안 돼. 원인 찾아서 고쳐줘. |
| jev | baseline | exp-064 | 기존 v1 | L2→L3 | L3 | 0.000 | Set up a GitHub Actions matrix for Python 3.10-3.12 with a shared cached venv and a separate lint job, and make release.yml depend on both. |
| jev | baseline | exp-068 | 기존 v1 | L2→L3 | L3 | 0.000 | Replace the ~40 logger.info(...) calls with the new log_event() helper, keeping the same fields as today. |
| jev | baseline | exp-069 | 기존 v1 | L5→L3 | L3 | 0.550 | 부하 걸릴 때만 가끔 주문이 두 번 결제돼. 로그엔 같은 payment_intent로 요청이 2번 찍혀. 원인 찾고 고쳐줘. |
| jev | baseline | exp-090 | 기존 v1 | L5→L4 | L4 | 0.980 | Plan the change of orders primary key from integer id to UUID, including 6 dependent foreign keys and an online backfill. Draft the plan and wait. |
| jev | baseline | exp-092 | 기존 v1 | L2→L1 | L1 | 0.000 | GitHub Actions에 pip 캐시 단계 넣어서 CI 시간 줄여줘. |
| nimble | baseline | seed-016 | 합본, 기존 v1 | L2→L3 | L3 | 0.005 | Replace the ad-hoc logging calls in the worker modules with the structured logger and keep the log fields stable |
| nimble | baseline | seed-024 | 합본, 기존 v1 | L4→L3 | L3 | 0.057 | Introduce an event bus between the order and notification services and migrate direct calls to events |
| nimble | baseline | seed-026 | 합본, 기존 v1 | L4→L5 | L2 | 0.284 | Migrate the orders table to a new schema with a changed primary key; write the migration and backfill |
| nimble | baseline | seed-027 | 합본, 기존 v1 | L5→L4 | L3 | 0.325 | Rewrite the authentication token signing and verification to rotate keys without invalidating live sessions |
| nimble | baseline | seed-028 | 합본, 기존 v1 | L5→L3 | L3 | 0.068 | Intermittent double charges appear under load; find the root cause across the payment, queue and retry code and fix it |
| nimble | baseline | exp-004 | 합본, 기존 v1 | L5→L4 | L3 | 0.314 | The partner payout job sometimes sends payouts twice after a crash mid-batch. Make it crash-safe and reconcile what already went out. |
| nimble | baseline | exp-014 | 합본, 기존 v1 | L2→L3 | L3 | 0.006 | Review this profile image upload code (type sniffing, 5MB cap, S3 storage) for problems. Don't change anything. |
| nimble | baseline | exp-019 | 합본, 기존 v1 | L2→L1 | L1 | 0.011 | 개발용 Docker Compose에 Postgres, Redis, 마이그레이션 컨테이너 추가하고 헬스체크 기준으로 기동 순서 맞춰줘. |
| nimble | baseline | exp-026 | 합본, 기존 v1 | L2→L1 | L1 | 0.002 | 학습 루프에 --max-grad-norm 옵션으로 gradient clipping 추가해줘. |
| nimble | baseline | exp-029 | 합본, 기존 v1 | L2→L3 | L3 | 0.001 | Rename the CLI option `--retries` to `--max-retries` in the command, its help text and the docs, keeping the old name as a hidden alias. |
| nimble | baseline | exp-035 | 합본, 기존 v1 | L4→L3 | L3 | 0.030 | DB 읽기 replica를 도입하고 조회 쿼리는 replica로 보내도록 데이터 접근 계층을 바꿔줘. |
| nimble | baseline | exp-043 | 합본, 기존 v1 | L5→L4 | L4 | 0.796 | Redesign the event-sourcing store so snapshots and replay stay consistent across a schema upgrade, without losing any events. |
| nimble | baseline | exp-057 | 합본, 기존 v1 | L4→L3 | L3 | 0.176 | 프로세스 메모리에 두던 세션을 Redis로 옮기는 diff야. 로그인/로그아웃/만료 흐름까지 포함돼 있어. 리뷰만 해줘, 수정하지 마. |
| nimble | baseline | exp-062 | 합본, 기존 v1 | L2→L3 | L3 | 0.006 | Check reports/monthly.sql: customers with no refunds seem to vanish. Review only, tell me what's wrong and don't edit. |
| nimble | baseline | exp-064 | 합본, 기존 v1 | L2→L1 | L1 | 0.004 | Set up a GitHub Actions matrix for Python 3.10-3.12 with a shared cached venv and a separate lint job, and make release.yml depend on both. |
| nimble | baseline | exp-068 | 합본, 기존 v1 | L2→L1 | L1 | 0.003 | Replace the ~40 logger.info(...) calls with the new log_event() helper, keeping the same fields as today. |
| nimble | baseline | exp-069 | 합본, 기존 v1 | L5→L3 | L3 | 0.104 | 부하 걸릴 때만 가끔 주문이 두 번 결제돼. 로그엔 같은 payment_intent로 요청이 2번 찍혀. 원인 찾고 고쳐줘. |
| nimble | baseline | exp-074 | 합본, 기존 v1 | L4→L3 | L3 | 0.181 | 모놀리식 Express 앱을 users, orders, catalog 모듈로 나누고 의존 방향 정리해줘. |
| nimble | baseline | exp-076 | 합본, 기존 v1 | L5→L3 | L3 | 0.098 | Rewrite JWT signing to support key rotation with kid, an overlap window and revocation, keeping old tokens valid until expiry. Check this diff, don't change anything. |
| nimble | baseline | exp-079 | 합본, 기존 v1 | L4→L3 | L3 | 0.090 | 공개 SDK 인증을 API key에서 OAuth2 client credentials로 바꾸고, 기존 key도 6개월은 지원해야 해. |
| nimble | baseline | exp-090 | 합본, 기존 v1 | L5→L4 | L4 | 0.509 | Plan the change of orders primary key from integer id to UUID, including 6 dependent foreign keys and an online backfill. Draft the plan and wait. |
| nimble | baseline | exp-092 | 합본, 기존 v1 | L2→L1 | L1 | 0.003 | GitHub Actions에 pip 캐시 단계 넣어서 CI 시간 줄여줘. |
| nimble | baseline | exp-107 | 합본, 기존 v1 | L4→L3 | L3 | 0.069 | 결제 모듈에 PG사 추상화 계층을 만들고 현재 단일 PG 연동을 어댑터로 옮겨줘. |
| nimble | baseline | add-036 | 합본 | L2→L1 | L1 | 0.002 | Add a --delimiter option to the existing TSV reader CLI, supporting exactly tab and comma through its existing parser argument. |
| nimble | baseline | add-042 | 합본 | L2→L3 | L3 | 0.006 | Review only: check this SQL query's LEFT JOIN predicate placement against the attached requirement to retain zero-match suppliers. No schema changes. |
| nimble | baseline | add-063 | 합본 | L4→L3 | L3 | 0.195 | Review only: check the design and patch replacing per-request database connections with a bounded shared connection pool across server modules. |
| nimble | baseline | add-070 | 합본 | L4→L3 | L3 | 0.087 | Add an explicit process supervisor to the existing single-process monitoring tool so collectors run in isolated child processes with a defined restart and result protocol. |
| nimble | baseline | add-083 | 합본 | L4→L3 | L3 | 0.095 | Separate our browser extension's privileged background operations from page scripts using typed message handlers and an explicit allowlist, updating all call sites. |
| nimble | baseline | add-084 | 합본 | L4→L3 | L3 | 0.059 | 여러 서비스에 복사된 세금 계산 규칙을 versioned pricing library로 통합하고 적용 버전이 invoice에 기록되게 변경해줘. 기존 운영 금액은 재계산하지 마. |
| nimble | baseline | add-093 | 합본, 새 150개 | L5→L4 | L4 | 0.672 | 멀티 스레드 영상 편집기에서 cancel 직후 간헐적으로 use-after-free가 난다. renderer와 background decoder의 수명 경합 원인을 찾아 고쳐줘. |
| nimble | baseline | add-095 | 합본, 새 150개 | L5→L4 | L4 | 0.709 | A storage compactor occasionally discards the newest version after power loss. Investigate write ordering, fsync and recovery logs; fix it and prove surviving records are retained. |
| nimble | baseline | add-096 | 합본, 새 150개 | L5→L3 | L3 | 0.026 | 운영 구독 청구에서 월말 시간대 전환 때 일부 계정만 두 달치가 청구된다. 스케줄 기준과 기간 계산, 재시도 기록을 분석해 원인을 고쳐줘. |
| nimble | baseline | add-100 | 합본, 새 150개 | L5→L4 | L4 | 0.680 | Kubernetes eviction 직후 외부 은행 송금은 성공했는데 내부 기록이 없어진다. 트랜잭션 경계, 응답 유실과 복구 재실행을 추적해 중복 송금을 막아줘. |
| nimble | baseline | add-101 | 합본, 새 150개 | L5→L4 | L4 | 0.884 | Diagnose rare divergent results in a distributed optimizer checkpoint restore across eight workers; some workers resume stale momentum and silently ruin training. Correct the state protocol. |
| nimble | baseline | add-105 | 합본, 새 150개 | L5→L4 | L4 | 0.735 | After network partitions, two nodes sometimes both become owner of the same writable volume and damage files. Reproduce the split-brain path and redesign fencing with a correctness argument. |
| nimble | baseline | add-113 | 합본, 새 150개 | L5→L3 | L3 | 0.091 | Plan only: redesign the hospital event reconciliation that currently associates sensor readings with the wrong patient only after reconnect bursts. Find a way to prove identity associations remain correct. |
| nimble | baseline | add-114 | 합본, 새 150개 | L5→L4 | L2 | 0.248 | 확정된 분석 없이 생산 검색 index 재구성이 원본 attachment를 가끔 덮어쓴다. indexer와 storage adapter의 경로 생성 및 retry 흐름을 추적해 데이터 손상을 막아줘. |
| nimble | baseline | add-118 | 합본, 새 150개 | L5→L2 | L2 | 0.088 | Plan only: transform the production tax ledger from net-only amounts to immutable line allocations; legacy rounding inconsistencies must be reconciled before originals are removed. |
| nimble | guide | seed-033 | 기존 v1 | L3→L2 | L2 | 0.106 | 계획만 세워줘: 테스트 스위트를 병렬 실행으로 바꾸는 방법 |
| nimble | guide | seed-034 | 기존 v1 | L3→L2 | L2 | 0.024 | Draft a plan for adding OAuth login to the web app, then wait for my approval |
| nimble | guide | seed-035 | 합본, 기존 v1 | L2→L3 | L3 | 0.012 | Review only: look at the changes in api/upload.py for bugs, do not modify anything |
| nimble | guide | seed-036 | 기존 v1 | L3→L5 | L2 | 0.384 | 리뷰만 해줘. 방금 바꾼 결제 모듈 코드에 문제가 없는지 검토해줘 |
| nimble | guide | exp-007 | 기존 v1 | L3→L2 | L2 | 0.018 | Airflow DAG에 증분 로딩 추가해줘. 먼저 어떻게 할지 계획을 보여주고 내가 OK 하기 전에는 코드 건드리지 마. |
| nimble | guide | exp-012 | 기존 v1 | L3→L4 | L3 | 0.205 | Add a nightly worker that emails digests via the queue. Two workers must never send the same digest. |
| nimble | guide | exp-014 | 합본, 기존 v1 | L2→L3 | L3 | 0.004 | Review this profile image upload code (type sniffing, 5MB cap, S3 storage) for problems. Don't change anything. |
| nimble | guide | exp-018 | 합본, 기존 v1 | L2→L1 | L1 | 0.025 | 화면 회전하면 ViewModel에서 목록이 두 번 로드돼. 한 번만 로드되게 고쳐줘. |
| nimble | guide | exp-019 | 합본, 기존 v1 | L2→L1 | L1 | 0.078 | 개발용 Docker Compose에 Postgres, Redis, 마이그레이션 컨테이너 추가하고 헬스체크 기준으로 기동 순서 맞춰줘. |
| nimble | guide | exp-039 | 기존 v1 | L3→L1 | L1 | 0.111 | 장바구니랑 위시리스트 상태를 Redux에서 Zustand로 바꿔줘. 컴포넌트 여러 개 걸려 있어. |
| nimble | guide | exp-062 | 합본, 기존 v1 | L2→L3 | L3 | 0.047 | Check reports/monthly.sql: customers with no refunds seem to vanish. Review only, tell me what's wrong and don't edit. |
| nimble | guide | exp-064 | 합본, 기존 v1 | L2→L1 | L1 | 0.009 | Set up a GitHub Actions matrix for Python 3.10-3.12 with a shared cached venv and a separate lint job, and make release.yml depend on both. |
| nimble | guide | exp-087 | 기존 v1 | L3→L1 | L1 | 0.093 | Move our CI from Jenkins to GitHub Actions: build, test, deploy stages with environment secrets and approval gates. |
| nimble | guide | exp-092 | 합본, 기존 v1 | L2→L1 | L1 | 0.003 | GitHub Actions에 pip 캐시 단계 넣어서 CI 시간 줄여줘. |
| nimble | guide | add-034 | 합본, 새 150개 | L2→L3 | L3 | 0.002 | Review only: a patch swaps two arguments to the existing payment SDK refund call in refunds.py. The approved SDK contract is attached and no workflow changes are intended. |
| nimble | guide | add-035 | 합본, 새 150개 | L2→L1 | L1 | 0.003 | 이미 soft-delete 필터가 있는 repository에서 count() 한 메서드만 필터를 누락했다. 다른 조회들과 같은 조건을 적용해줘. |
| nimble | guide | add-041 | 합본, 새 150개 | L2→L1 | L1 | 0.012 | Remove password values from this single debug log statement, retaining the user ID and error code; the log schema is already fixed. |
| nimble | guide | add-042 | 합본, 새 150개 | L2→L3 | L3 | 0.003 | Review only: check this SQL query's LEFT JOIN predicate placement against the attached requirement to retain zero-match suppliers. No schema changes. |

대상 오답 판정 68건 모두 기록. Nimble raw argmax가 L4 미만이고 P(L4)+P(L5)≥0.2이면 현재 승격 규칙이 L4/L5 중 확률이 높은 레벨로 올린다. Jev는 현재 확률·위험 임계값에 따른 L4/L5 강등 규칙을 적용한다.

## 모든 critical miss

| backend | 질문 | ID | 정답→예측 | 요청 |
|---|---|---|---|---|
| jev | guide | add-041 | L2→L1 | Remove password values from this single debug log statement, retaining the user ID and error code; the log schema is already fixed. |
| nimble | baseline | exp-110 | L3→L2 | 프로젝트 하위 라우트 전체에 admin/editor/viewer 역할별 접근 제어를 적용하는 계획만 세워줘. 구현은 하지 마. |
| nimble | baseline | add-118 | L5→L2 | Plan only: transform the production tax ledger from net-only amounts to immutable line allocations; legacy rounding inconsistencies must be reconciled before originals are removed. |
| nimble | guide | seed-034 | L3→L2 | Draft a plan for adding OAuth login to the web app, then wait for my approval |
| nimble | guide | exp-035 | L4→L1 | DB 읽기 replica를 도입하고 조회 쿼리는 replica로 보내도록 데이터 접근 계층을 바꿔줘. |
| nimble | guide | exp-087 | L3→L1 | Move our CI from Jenkins to GitHub Actions: build, test, deploy stages with environment secrets and approval gates. |
| nimble | guide | add-041 | L2→L1 | Remove password values from this single debug log statement, retaining the user ID and error code; the log schema is already fixed. |
| nimble | guide | add-070 | L4→L1 | Add an explicit process supervisor to the existing single-process monitoring tool so collectors run in isolated child processes with a defined restart and result protocol. |
| nimble | guide | add-113 | L5→L2 | Plan only: redesign the hospital event reconciliation that currently associates sensor readings with the wrong patient only after reconnect bursts. Find a way to prove identity associations remain correct. |

## 재현 자료와 검증

- 입력: `evaluation/corpus/corpus-v2.jsonl` (300 adjudicated), 새 부분: `evaluation/corpus/expansion-v2-labeled.jsonl` (150 adjudicated).
- 합본 출력: `runs/compare-v2-live-baseline-20261004.json` / `.md`, `runs/compare-v2-live-guide-20261004.json` / `.md`.
- 개별 출력과 메타데이터: `runs/compare-v2-live-{baseline,guide}-{jev,nimble}-20261004.json` 및 `-metadata.json`. 메타데이터는 호출 수·HTTP 상태·응답 모델·실측 지연·입력/질문 SHA256·git HEAD를 보존한다.
- 응답 모델: Jev `jev-1.13.0` 600건, Nimble `nimble` 600건. Nimble repo/user options는 None으로 기본값 사용.
- 조건별 case ID 300개 완전 일치, 레벨 n250, exact+over+under=250, target n300, 300회 전송, HTTP 200 300건, fallback0을 assert로 확인했다.
- Nimble 기존 질문의 v1 부분 150개 예측(분포·risk scores 포함)은 이전 v1 live 기록과 완전히 일치했다. 이번에는 150개 모두 다시 호출한 값이다.
- 단일 순차 A/B 측정이며 조건 순서 무작위화나 반복 실행을 하지 않았다. 질문 변경이 다른 질문의 분포에도 영향을 줄 수 있으므로 target/risk도 함께 보고했다.

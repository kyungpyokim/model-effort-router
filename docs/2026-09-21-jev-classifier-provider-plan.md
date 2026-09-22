# Jev 분류기 Provider 도입 계획 (v3)

> v1(8-signal 통합안)은 Opus 검토에서 반려됐고, v2는 조건부 승인(REVISE)을 받았다. v3는 v2 재검토의 지적(차단 1, 필수 4, 권장 6)을 모두 반영한 판이다.
> 핵심: 새 신호 스키마·Hard Rule 엔진·새 taxonomy를 만들지 않고, **기존 17-fact 계약을 지키는 분류기 provider 하나**로 Jev를 도입한다.
> **확정된 결정**: Jev가 unknown으로 답한 fact는 lookup 없이 **사용자에게 재질문**한다(§3.2).

## 1. 목표와 비목표

**목표**
- Jev를 기존 semantic classifier(`scripts/classifier.py`)와 같은 계약을 만족하는 **선택적 1차 분류기**로 추가한다.
- Jev가 없거나 실패해도 안전 정책이 약해지지 않는다.
- 승격은 측정 기준을 통과한 뒤에만 한다(shadow → primary).

**비목표**
- L1~L5, risk tier, 모델, effort, plan/review 여부를 Jev가 정하게 하지 않는다. 현행대로 결정적 규칙이 정한다.
- 새 task_type, 새 신호 스키마(8-signal), 연속 점수, 자기신고 confidence를 도입하지 않는다.
- 분류 이전 단계의 Hard Rule 엔진을 새로 만들지 않는다.
- Jev 결과에 대한 자동 lookup(저장소 읽기)을 하지 않는다.

## 2. 현행 구조 (변경하지 않는 것)

| 항목 | 현행 | 근거 |
|---|---|---|
| task_type | 6종: implementation, design, review, inspect, local_refactoring, architectural_refactoring. 모델 matrix의 행 키 | `rules.py:21`, `policy.py:102` |
| 분류 결과 정본 | 17 facts (yes/no/unknown 3상태 포함) | `rules.py:FACTS` |
| 검증·파생 | `validate_classifier_output(payload, source)`가 5키 정확 일치, FACTS 도메인, 교차 규칙, delegability, evidence를 검증하고 `evaluate_rules`로 level/tier/matched_rules/`unresolved`를 파생 | `classifier.py:218-252` |
| 레벨 결정 | facts → `DIFFICULTY_RULES` 중 매치된 최댓값 1개 (스택 없음) | `rules.py:evaluate_rules` |
| risk | risk_tier(standard/elevated/critical)와 L1~L5 두 축. 자동으로 critical이 되는 규칙은 `irreversible_or_ledger_or_crypto` 1건뿐이고 나머지는 `--critical` 수동 핀 | `rules.py:68` |
| unknown 처리 | 규칙을 매치시키지 않음 → (CLI classifier 경로만) bounded lookup 1회 → 사용자 질문(`prompt_unresolved`) → 미해결이면 exit 3 | `classifier.py:460-463`, `cli.py:245-250`, `cli.py:306` |
| 분류 실패 착지점 | L3, risk_flags 전부 False, facts 비어 있음, `source="fallback"` | `classifier.py:132-145` |
| fast path (2종) | ① trivial_edit: 17 facts 전량 일치 + 결정적 검증 명령이 있을 때만 plan/review 생략 ② inspect: task_type이 inspect이고 17 facts가 모두 있을 때 read-only 경로(검증 명령 불필요, L2/standard 상한) | `router.py:60-80`, `router.py:293`, `router.py:345-349` |
| 분류 호출 지점 | `cli.py:225`의 `router.classify_task(...)`. 그 뒤에 수동 프롬프트(fallback), `--answer` 적용, `prompt_unresolved`, 세션 저장이 이어진다. `route()`의 `classifier=` 파라미터는 이 결과를 그대로 넘기는 용도로 이미 점유돼 있다 | `cli.py:225-268`, `cli.py:253` |
| `source` 값 | 모델 id, `fallback`, `manual`, `reused`, `classification-file` | `classifier.py:143,387,472`, `router.py:258-263` |
| 핀 | `--task-type` + (`--level` 또는 `--critical`) 동시 지정이면 분류를 완전 우회. `--level` 단독은 분류 레벨의 **하한**일 뿐이다 | `router.py:314-329` |

## 3. 불변 조건 (모든 단계에서 유지)

1. **ClassificationResult의 정본은 17 facts + task_type(6종) + delegability + evidence다.** Jev 응답은 별도 검증 코드를 만들지 않고 `validate_classifier_output(payload, source="jev")`에 그대로 넘긴다. 이 함수가 `unresolved`를 파생하므로 우회하면 exit 3 경로가 죽는다. 검증 실패는 provider 실패로 처리하고 값 보정·추측은 하지 않는다.
2. **unknown 정책 (확정)**: Jev가 unknown으로 답한 fact는 **lookup 없이 사용자에게 재질문**한다.
   - 대화형(tty): 기존 `prompt_unresolved`가 `FACT_QUESTIONS` 문구로 묻는다.
   - 비대화형: 미해결 route로 종료하고 exit 3(`EXIT_NEEDS_ANSWER`). 사용자가 `--answer fact=값`으로 재실행한다.
   - 미해결 route는 실행하지 않는다(현행 동작 유지).
   - unknown ≠ no, unknown ≠ yes. 어떤 규칙도 unknown으로 매치되지 않는다.
   - 이 결정은 CLI classifier 경로의 기존 lookup을 바꾸지 않는다. Jev가 실패해 CLI classifier로 내려가면 현행대로 그쪽 lookup이 동작한다.
3. **분류 실패의 바닥은 L3이다.** 실패 시 L1/L2로 내려가지 않는다. 텍스트 키워드로 레벨을 낮추거나 올리지 않는다.
4. **plan/review 생략은 fast path 게이트만 허용한다.** trivial_edit(17 facts 전량 일치 + 결정적 검증 명령)과 inspect(read-only, L2 상한). 레벨 기반 생략은 없다. 분류 실패 route는 facts가 비어 두 게이트를 모두 통과할 수 없다(`set(facts) == set(FACTS)` 실패, 테스트로 고정한다).
5. **분류기 출력은 floor를 내리지 못한다.** floor는 facts에서 결정적 규칙이 파생한다. 핀의 정확한 의미는 §2 표와 §6을 따른다.
6. **fallback 트리거는 결정적 사유만 쓴다**: 프로세스 실패, 타임아웃, 응답·스키마 검증 실패, 키 미설정. 자기신고 confidence는 쓰지 않는다(`routing-policy.md:10`).
7. **`source`**: Jev 성공 시 `source="jev"`. 나머지는 §2 표의 현행 규약(모델 id / fallback / manual / reused / classification-file)을 그대로 둔다. 라우팅 결정에는 쓰지 않지만 shadow 비교와 세션 레코드 무효화(§8)에는 쓴다.

## 4. 구조

Jev는 `classify_task`의 앞단에서만 시도한다. `cli.py:225` 이후의 흐름(수동 프롬프트, `--answer`, `prompt_unresolved`, 세션 저장)은 손대지 않는다.

```text
cli.py: router.classify_task(...)
   │
   ▼
classify_task
   ├─ Jev 활성 && !repo_aware → JevProvider 시도 (짧은 타임아웃, 재시도 없음)
   │       ├─ 성공: Classification(source="jev") 반환   ← unknown이 있어도 lookup 없이 그대로 반환
   │       └─ 실패(§5.3): 아래로
   └─ 기존 경로: CLI classifier(+ bounded lookup) → 실패 시 fallback_classification (L3)
   │
   ▼
cli.py (변경 없음): fallback 수동 프롬프트 → --answer → prompt_unresolved → route()
   ▼
evaluate_rules(facts) → level / risk_tier      (기존)
   ▼
resolve_stages(matrix, task_type, level) → model / effort → fast path 게이트 → plan/implement/test/review (기존)
```

- **단일 소스 원칙**: 한 번의 분류에서 결과를 내는 provider는 하나다. Jev 결과와 CLI classifier 결과를 병합하지 않는다. lookup 병합(`merge_lookup`)은 CLI classifier 경로 내부에 남고 Jev에는 적용하지 않는다.
- `--repo-aware`가 켜져 있으면 Jev를 건너뛴다(Jev에는 저장소 접근이 없다).
- 구현은 `classifier.py`에 함수를 추가하고 `classify_task` 앞단에 분기를 넣는 수준으로 한정한다. `route()`와 정책 코드는 건드리지 않는다.

## 5. JevProvider 계약

### 5.1 입출력
- 입력: 사용자 작업 텍스트만. **저장소 내용·파일 경로·시스템 프롬프트 전문을 보내지 않는다.**
- 출력: 기존 분류 스키마(`CLASSIFIER_SCHEMA`)와 동일한 JSON. 검증은 §3.1대로 `validate_classifier_output`에 위임한다.
- fact 정의 문구는 기존 분류 프롬프트의 것을 재사용한다(판정 기준의 단일 출처). 정의를 Jev용으로 바꾸지 않는다.

### 5.2 인증·데이터
- 키는 환경 변수로만 받는다(코드·설정·route JSON·로그 기록 금지). 미설정이면 Jev를 건너뛴다.
- 작업 텍스트 원문은 로그에 남기지 않는다. 로그에는 source, 지연, 실패 종류, fact diff만 남긴다.
- 전송 범위, 보존 기간, 리전은 벤더 확인 후 §11에서 확정한다. 확정 전에는 기본 off.

### 5.3 실패 처리
| 상황 | 처리 |
|---|---|
| 키 없음 / 미설정 / kill switch / `--repo-aware` | Jev 호출 없이 기존 경로 |
| timeout / network / 5xx / rate limit / quota | 재시도 없이 기존 경로 |
| JSON 파싱 실패 / `validate_classifier_output` 실패 | 재시도 없이 기존 경로 |
| 성공했지만 일부 fact가 unknown | **정상 결과.** 그대로 반환하고 사용자 재질문(§3.2) |

### 5.4 지연 예산 (제안값, shadow 측정 후 확정)
- Jev 타임아웃 10s, 재시도 없음. Jev 실패 시 추가되는 지연은 이 1회분으로 한정한다.
- 현행 최악 경로 약 360s(90s × 재시도 1회 × 1차+lookup 2패스, `classifier.py:34,452-463`)는 `--classifier-timeout`(`cli.py:139`)으로 바뀔 수 있는 **현황 수치**이며 강제 예산이 아니다.

### 5.5 비용 트레이드오프 (확정 결정의 결과)
lookup이 없으므로 Jev 1차 분류에서 unknown이 남으면 CLI classifier 때보다 **사용자 질문이 늘 수 있다.** 이를 shadow 단계에서 측정한다(§8 unknown 비율). 질문이 과도하면 승격하지 않는다. 질문 수를 줄이려고 Jev가 unknown 대신 추측하게 만들지 않는다(프롬프트의 "yes just to be safe 금지" 원칙 유지).

## 6. 신뢰 경계

- 분류기(Jev 포함) 출력은 입력 텍스트가 조작할 수 있다는 전제로 다룬다. 현행 방어(텍스트를 데이터로 취급하는 프롬프트, read-only 도구 제한)를 유지한다.
- 조작 표면을 줄이는 구조:
  1. **fast path 게이트.** trivial_edit는 17 facts 전량 일치 + 결정적 검증 명령이 필요하다. inspect는 검증 명령이 필요 없고 read-only + L2/standard 상한으로 피해를 제한한다. 두 번째 경로는 "보안 코드 리뷰가 inspect로 오분류"되는 위험이 있으므로 shadow에서 별도 지표로 본다.
  2. **핀은 하향 상한이 아니다.** 완전 우회(`--task-type` + `--level`/`--critical`)는 분류 자체를 건너뛰어 조작에서 자유롭지만, `--level` 단독은 하한이다. 분류기가 레벨을 **올리는** 조작(비용 인플레이션)에 대해서는 어떤 핀도 상한을 제공하지 않는다. 이 비대칭을 수용한다.
  3. **하향 조작은 측정한다.** shadow의 하향 불일치율(§8)로 본다.
- **선택 사항(shadow 데이터가 필요성을 보여줄 때만)**: 작업 텍스트의 보안·DB·동시성 키워드를 결정적으로 스캔해, 히트하면 **fast path만 거부**한다. 키워드는 레벨을 올리지 않는다(`routing-policy.md:163`).

## 7. 결정적 정책

기존 `DIFFICULTY_RULES`를 **그대로 유지**한다. 합성은 max(멱등)만 쓰고 스택하지 않는다(`rules.py:192-199`). 새 규칙이 필요하면 `(target, rule_name, {fact: 값들})` 튜플로만 추가한다. v1 개념의 대응은 부록 A.

## 8. 롤아웃

| 단계 | 동작 | 진입 조건 |
|---|---|---|
| 0. off (기본) | Jev 호출 없음 | — |
| 1. shadow | 기존 경로로 라우팅하고 Jev는 **비차단**으로 별도 호출해 결과 diff만 기록. 라우팅 미반영 | §11 데이터 정책 확정 |
| 2. primary | §4 구조대로 Jev가 1차 | 승격 기준 통과 |
| kill switch | 환경 변수 하나로 즉시 단계 0 복귀 + 저장된 Jev 레코드 무효화 | 항상 유지 |

**shadow 실행 방식**
- route JSON 출력 이후 비차단으로 실행한다(사용자 지연 경로에 얹지 않는다). 실패는 무시한다.
- 샘플링 비율을 환경 변수로 제어한다(기본은 낮게).
- 결과는 route JSON이 아니라 별도 로그 파일에 쓴다.

**kill switch와 세션 재사용**
- `route_reuse`는 저장 레코드의 facts·level을 **재검증하지 않고** 그대로 쓴다(`router.py:240-258`). 그래서 Jev 유래 레코드가 TTL 4시간, 최대 10회(`route_reuse.py:24-25`) 동안 라우팅을 결정할 수 있다.
- 대응: `session_record`(`router.py:264`)에 `origin` 필드(분류 원본 source)를 추가하고, kill switch가 켜져 있으면 `reuse_blockers`(`route_reuse.py:85`)가 `origin == "jev"` 레코드를 차단한다. 이전 레코드에는 필드가 없으므로 `.get`으로 읽어 non-jev로 취급하고, `RECORD_VERSION`은 유지한다.

**shadow 지표**
- level 불일치율, 그중 **하향 불일치율**(Jev가 더 낮게 판정한 비율)을 별도 집계
- risk_tier 하향 불일치, risk_flag 누락률
- **unknown 비율**과 사용자 질문 수 증가분(§5.5)
- **task_type → inspect 오분류율**(특히 보안 관련 작업)
- 지연 p50/p95, 실패 종류별 비율, Jev 성공률(CLI classifier로 내려간 비율)

**승격 기준 (수치는 제안값, 골든셋 규모 확정 후 조정)**
1. **신설 평가(§10.5)** 기준으로 안전 위반 0건. 현행 `safety_violations`는 분류기를 호출하지 않는 규칙엔진 검증(`eval_router_performance.py:416-428`)에만 있고, 분류기를 실제로 부르는 `evaluate_classifier_benchmark`(`:570-641`)에는 안전 지표가 없다.
2. 하향 불일치율 ≤ X%, risk_tier 하향 불일치 0건
3. unknown 비율이 현행 CLI classifier(lookup 포함 최종 unresolved 비율) 대비 +Y%p 이내
4. p95 지연 ≤ 10s
5. 실제 트래픽 shadow 표본 N건 이상

> 골든셋은 facts 키(`BenchmarkCase.facts`, `:32`)로 작성돼 있어 Jev provider가 17 facts를 반환하면 fact 단위로 채점된다(`_grade_case`, `:518`).

## 9. 스키마·재사용 호환

- **route JSON**: 필드를 추가하지 않는다. `source="jev"`는 새 값일 뿐이고 `validated_commands`(`router.py:409-474`)는 `source`를 읽지 않으므로 `SCHEMA_VERSION`(7)은 유지한다. 필드를 추가하게 되면 v8로 올리고 `SUPPORTED_ROUTE_SCHEMA_VERSIONS`에 하위 버전을 유지한다.
- **세션 레코드**: `origin` 필드 추가(§8). `.get` 읽기라 하위 호환이며 `RECORD_VERSION` 유지.
- `load_reused_classification`은 저장된 facts를 `FACTS` 도메인으로 재검증하거나 `evaluate_rules`를 다시 돌리지 **않는다.** 이 사실을 전제로 설계한다(따라서 Jev가 만든 레코드가 저장되기 전에 §3.1 검증을 반드시 통과해야 한다).
- 세션 저장은 `source not in ("fallback","manual")`이고 `unresolved`가 없을 때만 일어난다(`cli.py:262`). Jev 결과에 unknown이 있으면 사용자가 답해 해소된 뒤에야 저장된다.
- **번들 동기화**: `scripts/sync_bundle.py`의 `SHARED` 목록에 없는 파일은 플러그인 사본에 복사되지 않는다(`sync_bundle.py:10-22`). 그래서 JevProvider는 신규 파일이 아니라 **이미 SHARED에 있는 `scripts/classifier.py`에 함수로 추가한다.** 신규 파일이 불가피하면 `SHARED`와 `validate_bundle.py`를 함께 갱신한다.

## 10. 구현 순서 (TDD, 단계별 커밋)

1. **선행 정리**: `scripts/rules.py`의 미사용 중복 함수 `is_read_only_inspect`, `is_trivial_edit_fast_path` 삭제. 후자는 정의되지 않은 `normalise_tier`를 호출하며(`rules.py:116`) `router.py`의 `TRIVIAL_EDIT_FACTS`와 기준이 다르다. 루트 `scripts/`만 편집하고 `python scripts/sync_bundle.py`로 플러그인 3곳에 반영한다(`.worktrees/` 하위 사본은 범위 밖).
2. **체인 골격 + 회귀 테스트**: `classify_task` 앞단 분기 추가. 테스트: Jev 활성 시 성공 결과 사용, 실패 종류별 기존 경로 이동, `--repo-aware`이면 Jev 무호출, 전부 실패 시 L3 + facts 비어 두 fast path 모두 불가.
3. **JevProvider**: 응답을 `validate_classifier_output(payload, source="jev")`에 위임. 테스트: 도메인 밖 값 거부, **unknown이 남으면 `unresolved`가 채워지고 lookup 없이 반환**, 키 없음 시 무호출, 타임아웃 시 재시도 없음.
4. **unknown 재질문 회귀 테스트 (필수)**: Jev unknown → tty에서 `prompt_unresolved` 호출, 비대화형에서 exit 3, `--answer`로 해소 후 정상 route. 미해결 route가 실행·저장되지 않음.
5. **shadow 러너 + 킬 스위치**: 비차단 실행, 샘플링, 별도 로그, env 플래그(기본 off). `session_record.origin`과 `reuse_blockers` 차단 추가.
6. **평가 신설·확장**: `evaluate_classifier_benchmark`에 안전 지표(기대 tier/flag 누락, 하향 불일치)를 추가하고 **케이스별 provider 귀속(`actual.source == "jev"`)을 기록해 Jev가 실제로 답한 케이스만 Jev 점수로 채점**한다. 현행은 Jev 실패 후 CLI가 답해도 `source != "fallback"`이라 집계에 섞인다(`eval_router_performance.py:609`). 주입은 `classifier: Callable[[str, str], Classification]`(`:571-573`)로 가능하다. 리포트에 하향 불일치율·unknown 비율·지연·inspect 오분류율을 낸다.
7. **승격 판단**: shadow 데이터로 §8 기준을 평가하고, 통과 시에만 단계 2로 올린다.
8. (선택) §6의 fast-path 거부용 키워드 스캔.

## 11. 열린 질문

- Jev의 실제 API 명세: 출력 타입(v1 원문 4.3의 "Noul"은 타입 표기 오타로 보이며 확인 필요), 구조화 출력 지원 여부, 인증 방식.
- 데이터 정책: 작업 텍스트가 벤더로 전송되어도 되는가, 보존 기간, 리전. 답이 "아니오"면 Jev는 도입하지 않는다.
- 플랫폼별(codex / claude-code / antigravity) 기본 활성화 여부.
- 승격 기준의 X, Y, N 값과 shadow 샘플링 기본 비율.
- Jev를 쓰는 동기가 지연/비용 절감인지 정확도 향상인지. lookup을 쓰지 않는 결정 때문에 사용자 질문이 늘 수 있어(§5.5), 동기에 따라 unknown 비율 기준의 무게가 달라진다.

## 부록 A. v1 개념 → 현행 대응

| v1 항목 | 처리 |
|---|---|
| task_type 8종 | 폐기. 6종 유지. Jev는 6종 중 하나를 반환 |
| complexity 0~5 | 폐기. `files_touched`, `needs_new_structure`, `fix_or_result_known` 등 facts가 표현 |
| deep_reasoning | `intermittent_or_concurrency`, `needs_new_structure`, `fix_or_result_known` |
| scope | `files_touched`, `crosses_module_boundary`, `crosses_service_boundary` |
| blast_radius | `blast_radius`(narrow/broad/unknown), `silent_failure_material_harm`, `irreversible_or_ledger_or_crypto` |
| underspecified | `fix_or_result_known`, unknown 3상태 + 사용자 재질문 |
| security | `security_domain`, `changes_security_or_payment_logic`, `reviews_security_sensitive_code`, `changes_trust_boundary` |
| concurrency | `intermittent_or_concurrency` |
| Hard Rule / Critical Override | 폐기. 자동 critical은 `irreversible_or_ledger_or_crypto` 규칙 1건뿐이고 그 외 critical은 사용자 `--critical` 수동 핀. 이 범위를 넓히려면 §7의 규칙 추가 절차로만 한다 |
| 최소 레벨 강제 | `DIFFICULTY_RULES`의 floor 규칙(max 합성) |
| Jev fallback 체인 | §4, §5.3 |
| Conservative Rule Fallback | 기존 `fallback_classification`(L3 바닥) 유지. 키워드 상향·L1/L2 하향 없음 |
| Plan/Review 레벨별 생략 | 폐기. fast path 게이트(trivial_edit, inspect)만 |
| 8-signal 로깅 | 폐기 |

# 최종 검증: Claude 경로 프롬프트 · task_type 경계 · 품질 게이트 (2026-09-25)

검증 대상: `main` @ `dbc5f31` (플러그인 번들 v3.1.0). 이 문서의 수치는 모두 실제 실행 결과에서
인용했고, 각 절에 출처 아티팩트와 재현 명령을 둔다. Jev 기준선은 `docs/routing-ceiling.md`의
동결 표를 인용하되, 이번 라운드가 Jev payload를 바꾸지 않았다는 사실을 git diff로 함께 검증한다(§2.2).

## 0. 판정 요약

| 대상 | 판정 | 근거 |
|---|---|---|
| 품질 게이트 | **통과** | ruff clean · 489 tests / 945 subtests · bundle validation |
| Jev 분류 기준선 | **동결 유지** | exact 93% · under-route 0 · safety 0 · payload 무변경(§2.2) |
| Claude Code 경로 | **수용** | focused 30: exact 11→19, under-route 13.33%→0, safety 4→0 |
| task_type 경계 | **기각·기록** | 문구 변형 6종 전부 anchor 회귀, 정의 변경 없음 (ceiling §Task-type) |

## 1. 품질 게이트

| 게이트 | 명령 | 결과 |
|---|---|---|
| Lint | `ruff check scripts tests` | `All checks passed!` (120 → 0, `ruff.toml` 추가) |
| 테스트 | `python3 -m pytest tests/ -q` | `489 passed, 945 subtests passed` (23.7s) |
| 번들 | `python3 scripts/sync_bundle.py && python3 scripts/validate_bundle.py` | `bundle validation passed` (v3.1.0, 플러그인 사본 byte-equal) |

ceiling 문서의 unfreeze 조건 핀(`**Unfreeze when.**` 8개)도 테스트 스위트에 포함되어 함께 통과한다.

## 2. Jev — 분류 기준선 (동결)

### 2.1 기록값

`docs/routing-ceiling.md` "Current baseline" (2026-09-24, 커밋 `6c3a204`, live Jev `primary`,
platform `codex`, 전 100케이스, 독립 2런 — 라우팅 차이 0):

| Metric | Value |
|---|---|
| Routing accuracy (exact: level + tier + unresolved contract) | 93% (93/100) |
| Strict routing accuracy (live-path noul unknowns counted as misses) | 89% |
| Level accuracy / within ±1 | 95% / 98% |
| Tier accuracy | 98% |
| Over-route | 5 (mean distance 1.4, max 2) |
| Under-route | 0 |
| Safety / downward level / downward tier | 0 / 0 / 0 |
| Inspect misclassifications | 0 |
| Critical recall / elevated recall | 100% / 100% |
| Labelled fact accuracy | 95.0% (run1 94.94, run2 95.0) |
| Task-type accuracy / model+effort profile | 92% / 92% |
| Unknown facts | 40 (2.35%) |
| Unresolved (ASK) agreement | 37 / 39 applicable |
| Cost inflation | 1.045 (943 vs 902 expected units) |
| Classifier fallbacks / run-to-run instability | 0 / 0 cases |

아티팩트: `/tmp/jev_ft2_run1.json`, `/tmp/jev_ft2_run2.json` — 두 런 모두 exact 93/100, strict 89,
level 95.0, ±1 98.0, tier 98.0, task-type 92.0, profile 92.0, under 0, safety 0, fallback 0.

### 2.2 payload 무변경 검증

이번 라운드가 Jev 라우팅에 영향을 주지 않았다는 근거:

```text
git diff 6c3a204 HEAD -- scripts/jev_provider.py  → 변경 없음
git diff 6c3a204 HEAD -- scripts/rules.py         → 주석/줄바꿈만 (문자열 상수 변경 없음)
git diff 6c3a204 HEAD -- scripts/classifier.py    → Claude 프롬프트 2조항 + lint용 lambda→def 변환만
```

Jev가 받는 payload(사실 질문·기준 문자열)와 Jev 경로 코드는 `6c3a204`와 동일하다. 따라서 §2.1의
기록값은 현재 `main`에서도 유효하다. (Jev 재실행은 이번 라운드에 하지 않았다 — 재측정 명령은 §5.)

## 3. Claude Code 경로 — 프롬프트 라운드 (focused 30 A/B)

측정 조건: canonical evaluator(`eval_router_performance.evaluate_classifier_benchmark`), 직접
Anthropic(로컬 CCR 게이트웨이 우회), platform `claude-code`,
`PRIMARY_CLASSIFIER_CONFIG["claude-code"]["model"]="sonnet"`, repo-aware `classify_task_single`
(저장소 읽기 허용), fallback 0, 케이스 = 하네스 `FOCUSED` 30 (부록 A).

| 지표 | before | after | Δ |
|---|---:|---:|---:|
| exact (level + tier + unresolved) | 11/30 (36.67%) | **19/30 (63.33%)** | +8 |
| level accuracy | 66.67% | **76.67%** | +10.0pp |
| level ±1 | 83.33% | **90.0%** | +6.7pp |
| tier accuracy | 96.67% | 96.67% | 0 |
| labelled fact accuracy | 92.35% | **94.9%** | +2.55pp |
| task-type accuracy | 93.33% | 93.33% | 0 |
| model+effort profile | 50.0% | **70.0%** | +20.0pp |
| under-route | 4 (13.33%) | **0** | −4 |
| over-route | 6 (20.0%) | 7 (23.33%) | +1 |
| 안전 위반(safety violations) | 4 | **0** | −4 |
| 평균 부호 거리 | +0.033 | +0.333 | 상향 |
| 비용 팽창 | 1.082 (211/195) | 1.241 (242/195) | +0.159 |
| classifier fallbacks | 0 | 0 | 0 |

### 3.1 케이스 이동 (6건)

| 케이스 | before | after | 기대 | 판정 |
|---|---|---|---|---|
| `L2_review_small_pr` | L1 | L2 | L2 | under-route 해소 |
| `L4_review_xss_sanitization` | L2 | L4 | L4 | under-route 해소 |
| `L4_review_path_traversal_sanitization` | L2 | L4 | L4 | under-route 해소 |
| `L4_review_ssrf_url_validation` | L2 | L4 | L4 | under-route 해소 |
| `L4_review_password_hashing_rounds` | L4 | L5 | L4 | 새 over-route (안전 방향, 문서화된 잔여) |
| `L2_unknown_module_boundary_and_scope` | L3 | L4 | L2 | over-route 심화 (+1 → +2, 기존 동결 케이스) |

### 3.2 조항별 fact 영향 (focused 30)

| fact | before | after | 비고 |
|---|---:|---:|---|
| `files_touched` | 63.33% (FP 7) | **83.33% (FP 2)** | evidence-only 조항 |
| `reviews_security_sensitive_code` | 86.67% (FN 4) | **96.67% (FN 1)** | security_domain 독립 조항 |
| `security_domain` | 96.67% | 90.0% | `L4_review_password_hashing_rounds` 1건 |
| `crosses_module_boundary` | 90.0% | 86.67% | `L2_unknown_module_boundary_and_scope` 1건 |
| unknown facts | 10 (1.96%) | 14 (2.75%) | — |

### 3.3 대가와 수용 근거

- **목적 달성**: under-route(안전 위반) 4 → 0, 새 문구는 보안 리뷰 3건(XSS·path traversal·SSRF)과
  `L2_review_small_pr`의 과소 라우팅을 정확히 제거했다.
- **대가**: over-route 6 → 7, 비용 팽창 1.082 → 1.241. 상향 실수는 안전 방향이며(평균 부호 거리
  +0.333), 새 over-route 1건과 심화 1건 모두 안전 방향이다.
- **의도적 제외**: `crosses_module_boundary` over-fire(full FP 5 / FN 2)는 이 커밋에서 다루지 않았다.

### 3.4 동기화된 변경 (커밋 `d0e0c4f`, 13 files)

- `scripts/classifier.py`: `CLASSIFIER_PROMPT` 2조항 (evidence-only `files_touched`,
  `security_domain` 독립 `reviews_security_sensitive_code`)
- `references/routing-policy.md`: 미러 2행
- `scripts/rules.py`: 계약 주석
- `tests/test_router.py`: 프롬프트/정책 패리티 핀
- `plugins/{codex,claude,antigravity}-model-effort-router/`: 동기화 사본 9개 파일

## 4. Claude Code 경로 — 전체 100 (참고)

라운드 후 1회, §3과 같은 조건. quota로 83건 채점.

| 지표 | 값 |
|---|---:|
| 채점 | 83/100 (17건 미채점) |
| exact | 65/83 (78.31%) |
| level accuracy / ±1 | 89.16% / 96.39% |
| tier accuracy | 98.8% |
| labelled fact accuracy | 96.81% |
| task-type accuracy | 91.57% |
| model+effort profile | 78.31% |
| under-route / downward level / downward tier | 0 / 0 / 0 |
| 안전 위반 | 0 |
| over-route | 9 (10.84%) |
| 비용 팽창 | 1.133 (469/414) |
| classifier fallbacks | 17 (= 미채점 17건) |
| unknown facts | 43 (3.05%) |
| critical recall | **미측정** |
| elevated recall | 100% (2/2) |

profile 불일치 18건의 구성: unresolved 계약 불일치로만 발생한 12건 + 그 외 프로필(모델/스테이지
또는 mode) 불일치 6건.

**한계**: 미채점 17건은 정확히 꼬리 구간(L5E 7 + L5C 10)이고, critical 표본이 여기에만 있어
critical recall은 미측정이다. §4는 §3(focused 30)의 보조 근거로만 사용한다.

## 5. 재현

```bash
# 1) 품질 게이트
ruff check scripts tests
python3 -m pytest tests/ -q
python3 scripts/sync_bundle.py && python3 scripts/validate_bundle.py

# 2) Jev 기준선 (전 100, platform codex)
export MODEL_EFFORT_ROUTER_JEV_API_KEY=...    # TypeSafe stage key
export MODEL_EFFORT_ROUTER_JEV_STAGE=primary
export MODEL_EFFORT_ROUTER_JEV_ENDPOINT=https://api.typesafe.ai/v1/systemone
python3 scripts/eval_router_performance.py --live-classifier --platform codex --json > /tmp/jev_run.json

# 3) Claude Code 경로 (direct Anthropic, CCR 우회)
MER_REPO=$PWD python3 claude_eval_ab.py after                 # focused 30
MER_CASES=full MER_REPO=$PWD python3 claude_eval_ab.py full   # 전체 100 (quota 주의)
```

세션 하네스는 저장소 밖(세션 임시 디렉터리)에 있다: `claude_eval_ab.py`(canonical 지표),
`claude_assessor_ab.py`(케이스별 필드 비교), `claude-direct`(CCR 우회 래퍼 —
`claude --settings '{"env":{...api.anthropic.com...},"apiKeyHelper":""}'`). 하네스는 저장소 코드를
수정하지 않고 커스텀 classifier 콜러블만 주입한다.

## 6. 미검증·남은 항목

- Claude full-100 critical recall: 표본 0 (미채점 17건 구간) — 별도 측정 필요.
- Claude 경로 잔여(문서화됨, 이번 커밋에서 제외):
  - `crosses_module_boundary` over-fire: full run FP 5 / FN 2.
  - `files_touched` FP 1 (full).
  - `L4_review_password_hashing_rounds`: `security_domain` crypto vs auth.
- Jev: task-type 92% / profile 92% — corpus 라벨 긴장. `docs/routing-ceiling.md`의 unfreeze 조건 참조.
- Jev 재측정은 이번 라운드에 없음(§2.2로 동결 유지 판단; 재측정은 §5-2).

## 7. 증거 아티팩트 (세션 로컬 `/tmp`)

| 파일 | 내용 |
|---|---|
| `/tmp/jev_ft2_run1.json`, `jev_ft2_run2.json` | Jev 동결 기준선 2런 (§2.1) |
| `/tmp/claude_eval_before.json` | focused 30 before (canonical) |
| `/tmp/claude_eval_after.json` | focused 30 after — **커밋된 문구** |
| `/tmp/claude_eval_after_v1.json` | 문구 v1 측정 (exact 15/30, profile 56.67% — 미채택) |
| `/tmp/claude_eval_full.json` | 전체 100 (§4) |
| `/tmp/claude_assessor_before.json`, `claude_assessor_after.json` | focused 30 케이스별 ft/rev/secdom/level/tier 비교 |
| `/tmp/tasktype_before2.json` | task_type 45케이스 하네스 기준선 (task_type 37/45, profile 39/45) |
| `/tmp/tasktype_g1{,b,c,d}.json`, `/tmp/tasktype_g2{,b}.json` | 문구 변형 6종 측정 |
| `/tmp/jev_tt_run1.json`, `jev_tt_run2.json` | Jev task_type 런 2회 (task-type 92%, 두 런 동일) |

## 부록 A. focused 30 케이스

```text
L4_review_jwt_auth_middleware, L4_review_session_cookie_flags, L4_review_xss_sanitization,
L4_review_sql_injection_defense, L4_review_csrf_protection_tokens, L4_review_rate_limiting_headers,
L4_review_path_traversal_sanitization, L4_review_ssrf_url_validation,
L4_review_password_hashing_rounds, L5E_deploy_approval_bypass_removed, L1_code_formatting,
L1_rename_local_variable, L2_multifile_feature_scope_unknown, L2_unknown_module_boundary_and_scope,
L2_unknown_security_change_is_not_a_floor, L3_open_ended_investigation, L3_investigate_test_flakiness,
L3_diagnose_broken_pipeline_stage, L4_cross_module_refactor, L4_db_data_migration,
L5_open_result_across_modules, L5E_security_oauth_token_refresh, L1_doc_typo_fix,
L1_license_header_update, L2_simple_bug_fix, L3_sync_enum_two_files, L3_add_feature_controller_service,
L4_large_scale_files_change, L2_review_small_pr, L1_inspect_git_clean_status
```

# 작업 히스토리: 분류기 라운드 3종 — Claude 프롬프트 · task_type · lint (2026-09-25)

이 문서는 2026-09-25 라운드의 작업 기록이다. 측정 수치의 인용과 재현 방법은
`docs/2026-09-25-final-verification.md`에 정리했다(이 문서는 흐름과 판정 기록).

## 0. 요약

| # | 라운드 | 목표 | 변경 | 측정 | 판정 | 커밋 |
|---|---|---|---|---|---|---|
| 1 | Claude 프롬프트 2조항 | Claude 경로 under-route·안전 위반 제거 | `CLASSIFIER_PROMPT` 2조항 + 정책 미러 + 테스트 핀 | focused 30 A/B: exact 11→19, under 4→0, safety 4→0 | **수용** | `d0e0c4f` |
| 2 | task_type 경계 | 8개 task_type 미스 축소 | (문구 변경 없음) ceiling 문서 기록만 | 45케이스 하네스 6변형 전부 anchor 회귀 | **기각·기록** | `bcef3ff` |
| 3 | 품질 게이트 | lint 정리 | ruff 자동/수동 수정 + `ruff.toml` | 120 → 0 findings, 489 tests | **수용** | `dbc5f31` |

적용한 원칙: 측정 없이 문구를 바꾸지 않는다 · 라운드마다 독립 런 · fallback 0 확인 ·
안전 지표(under-route·safety·critical recall)를 최우선 · 회귀가 있는 변형은 채택하지 않는다 ·
Jev 라운드가 아니면 Jev payload를 건드리지 않는다.

## 1. 배경 (이전 라운드)

- 2026-09-23~24: fact 정의 라운드(`571676e`, `959ec64`, `9d16161`, `1f2b5f1`, `6c3a204`)로 Jev 기준선을
  exact 93%까지 올리고, `docs/routing-ceiling.md`에 천장을 동결(`7f3ea9b`, `ad572fb`).
- `803cf4e`(3.1.0 번들)까지 `origin/main`에 반영된 상태에서 시작.
- 범위: (a) Claude Code 경로 `CLASSIFIER_PROMPT`, (b) Jev task_type 경계, (c) lint.
  Jev 라우팅 정의 자체는 범위 밖.

## 2. 라운드 1 — Claude 프롬프트 2조항 (`d0e0c4f`, 03:10)

**문제.** focused 30 before: exact 11/30, under-route 4건(13.33%), 안전 위반 4건, profile 50%.
under-route는 전부 보안 리뷰 계열(리뷰 3건 + `L2_review_small_pr`)이었고, `files_touched` fact 63.33%,
`reviews_security_sensitive_code` 86.67%로 낮았다.

**후보와 측정.**

- v1 문구: exact 15/30, level 76.67%, fact 94.31%, profile 56.67% — 미채택.
- v2 문구(채택): exact 19/30, level 76.67%, fact 94.9%, profile **70.0%**.

**최종 조항 2개.**

1. `files_touched` — 증거 기반만 인정: 명시된 개수, 파일/모듈/서비스/패키지 목록, diff, 저장소 읽기
   결과. 역할·레이어 서술이나 "복잡해 보임"으로 추정 금지, 증거가 없으면 unknown. (범위 서술은
   개수 진술이 아니다.)
2. `reviews_security_sensitive_code` — `security_domain`과 독립. 입력 방어(output escaping, injection,
   path traversal, SSRF/URL 처리)는 도메인이 none으로 남아도 리뷰 fact = yes.

**결과.** exact 11→19, level 66.67→76.67, ±1 83.33→90.0, fact 92.35→94.9, profile 50.0→70.0,
under 13.33→0, safety 4→0, over 6→7, 비용 팽창 1.082→1.241.
케이스 이동 6건: XSS·path traversal·SSRF 리뷰 L2→L4(해소), `L2_review_small_pr` L1→L2(해소),
`L4_review_password_hashing_rounds` L4→L5(안전 방향 신규 over-route),
`L2_unknown_module_boundary_and_scope` L3→L4(심화, 기존 동결 케이스).

**커밋 범위.** repo 4개 파일 + 플러그인 사본 9개 = 13 files. `references/routing-policy.md` 미러 2행,
`scripts/rules.py` 계약 주석, `tests/test_router.py` 패리티 핀 포함.
**의도적 제외.** `crosses_module_boundary` over-fire(full FP 5 / FN 2) — 별도 라운드로 남김.

**보조 측정(full 100, quota로 83 채점).** exact 65/83(78.31%), level 89.16, ±1 96.39, tier 98.8,
fact 96.81, under 0, safety 0, down-level/tier 0, profile 78.31. 미채점 17건은 L5E 7 + L5C 10 꼬리 →
critical recall 미측정.

## 3. 라운드 2 — task_type 경계: negative result (`bcef3ff`, 04:23)

**문제.** 전 100 두 런에서 task_type 92%(8 미스): L1 tidy-up 3건(`L1_markdown_link_fix`,
`L1_comment_spelling_fix`, `L1_trailing_whitespace_cleanup`)과 `L3_refactor_logger_four_files`가
local_refactoring 대신 implementation으로, `L4_sdk_breaking_method_rename`,
`L5E_multi_service_frontier_redesign`, `L5C_cryptographic_key_rotation`가 architectural 대신
implementation으로, `L4_consolidate_validation_schemas`가 local로.

**시도 (45케이스 포커스 하네스, 기준선 task_type 37/45 · profile 39/45).**

| 변형 | 측정 결과 |
|---|---|
| local_refactoring 확장 4종 | tidy-up을 못 옮기거나 `L1_doc_typo_fix`/`L1_license_header_update`/`L1_bump_version_string`/`L4_large_scale_files_change` 회귀 |
| architectural 텍스트 확장 1종 | 타깃 4건 해결, 그러나 `L3_extract_shared_utility_three_files`/`L4_rename_type_across_ten_files`/`L4_large_scale_files_change` 회귀 |
| fact-gated architectural 1종 | 게이트는 의도대로 동작, 같은 3건 회귀 — 추가 서술 자체가 구조 신호로 읽힘("across N …") |

**정적 검증.** `jev_tasktype_rules.py`(규칙 논리만 적용)로는 8/8 해결·corpus 라벨 0 flips —
실패 원인은 규칙 논리가 아니라 live 모델의 경계 판단이다. 라벨 쌍 2개가 어떤 단일 문구로도 모순:
`consolidate`↔`extract_shared`, `comment_spelling`↔`doc_typo`.

**판정.** 정의 무변경. 근거·측정 변형·unfreeze 조건을 `docs/routing-ceiling.md`의
"Task-type boundary family" 절에 기록. task_type은 level/tier 규칙에 입력되지 않아(exact 무영향)
matrix 행(모델+effort)만 결정한다는 점도 함께 기록.

## 4. 라운드 3 — 품질 게이트: ruff (`dbc5f31`, 04:40)

**문제.** ruff 0.15.20 기본 규칙(E4/E7/E9/F) 120 findings — F401 91, E402 14, F811 5, E731 4, E741 3,
E702 2, F841 1. 설정 파일 없음(전부 기본값).

**사고와 교훈.** `ruff --fix`를 그대로 돌리면 재수출 import(`router.py`가 `classifier`/`commands`에서
가져와 테스트·스킬이 `router.X`로 사용)가 삭제되어 `router.py` import 체인이 깨졌다
(`ImportError: cannot import name 'FACT_QUESTIONS'`). 전부 원복하고, `ruff.toml`의
per-file-ignores로 의도적 패턴을 문서화한 뒤 다시 적용:

- E402 — scripts/tests가 `sys.path`에 scripts 디렉터리를 넣은 뒤 형제 모듈을 import하는 관용구.
- F401 — `classifier.py`, `cli.py`, `commands.py`, `router.py`는 재수출 허브다.

**결과.** 120 → 0. 자동 fix 14건, 수동 13건: `commands.py` 그림자 import·죽은 할당 제거,
`classifier.py`의 `unwrap` 람다 3개 → 중첩 def, 테스트의 `l` 이름 → `lv`, 세미콜론 문장 분리,
테스트 람다 → def. 플러그인 사본은 `sync_bundle.py`로 재생성.
**검증.** ruff clean, 489 tests/945 subtests, bundle validation. (사용자 커밋 `c5e273e`가 이어서
`.vscode` 설정을 추가했다.)

## 5. 철회·취소된 작업

- Claude-as-classifier 계측 중단 — 분류 기준은 Jev 하나로 유지(Jev-only). Claude는
  `platform=claude-code`의 실행자로만 측정한다.
- 17케이스 grading job 취소(실행 전, Claude 호출 0).
- task_type 문구 변형 6종은 전부 되돌림 — 작업 트리에 흔적 없음.

## 6. 열린 항목

| 항목 | 상태 | 트리거 |
|---|---|---|
| Jev task-type 92% / profile 92% | 동결 | corpus 라벨 조정 (ceiling unfreeze 조건) |
| Claude `crosses_module_boundary` over-fire | 미해결 | 별도 라운드 |
| Claude full-100 critical recall | 미측정 | L5E/L5C 꼬리 채점 |
| `L4_review_password_hashing_rounds` 도메인(crypto vs auth) | 문서화된 잔여 | — |

## 7. 커밋 목록

| 커밋 | 시각 | 내용 | 푸시 |
|---|---|---|---|
| `d0e0c4f` | 09-25 03:10 | fix(classifier): evidence-only files_touched and reviews independent of security_domain | origin/main |
| `bcef3ff` | 09-25 04:23 | docs(routing): record the task_type boundary family in the ceiling doc | origin/main |
| `dbc5f31` | 09-25 04:40 | chore(lint): clean ruff findings across scripts and tests | origin/main |
| `c5e273e` | 09-25 04:42 | chore(vscode): add extensions and settings for Python formatting with Ruff (사용자) | origin/main |

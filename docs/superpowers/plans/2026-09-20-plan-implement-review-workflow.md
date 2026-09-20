# Plan → Implement → Review 워크플로우 강제 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 코드 변경 작업을 `상위 모델 Plan → 저비용 모델 Implement → 결정적 Test → 상위 모델 Review`로 launcher가 강제하고, Read-only 조회와 사소한 수정은 Fast Path로 저비용 모델 단독 처리한다.

**Architecture:** 분류 체계(L1~L5, 6 factor, risk tier)와 `pipeline.py` 상태 머신은 유지한다. 새 계획 단계는 새 matrix 항목이 아니라 기존 `design` 행(Sol/Opus)에서 파생하고, 구현 단계는 기존 matrix + L2 refinement를 그대로 쓴다. Fast Path는 L1 + 명시적 gating 조건일 때만 Plan/Review를 건너뛴다.

**Tech Stack:** Python 3 stdlib, `unittest`/pytest (기준선 347 passed), bash launchers, JSON config.

## Global Constraints

- `unknown`은 yes/high risk/high difficulty/escalation 신호가 아니다. 상위 모델 재분류 금지 (이미 `unresolved_facts` 경로로 구현됨, 건드리지 않는다).
- 난이도(L1~L5)와 위험도(risk tier)는 분리한다. Risk tier는 Plan/Review effort만 올린다: standard=high, elevated=xhigh, critical=max. 구현 모델은 올리지 않는다.
- Sol/Opus는 Plan·Review·Re-plan 담당. 구현·Fix는 Luna/Terra, Haiku/Sonnet. Luna XHigh/Max는 일반 구현 경로 금지.
- 테스트 실행에는 LLM을 쓰지 않는다 (`pipeline.run_tests`, 이미 구현됨).
- Review FAIL 시 Review 모델이 직접 수정하지 않는다 (`read` access, 이미 구현됨).
- 모델 ID는 `config/model-map.json`이 단일 출처. 번들 루트의 `scripts/`·`config/`·`references/`만 편집하고 `python3 scripts/sync_bundle.py`로 plugin 사본을 동기화한다.
- 커밋 형식 `<type>: <description>`, 각 커밋 끝에 `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.
- 범위 밖 변경 금지: 기존 `SCHEMA_VERSION = 6` 유지 (route JSON 모양 불변, `mode`/`steps` 값만 달라짐). replay 계약이 바뀌는 Phase 4에서만 올린다.

---

## 현황 분석 (계획서 대비)

이미 구현됨 — 이번 계획에서 **다시 만들지 않는다**:

| 계획서 항목 | 위치 |
|---|---|
| L1~L5, 6 factor, `DIFFICULTY_RULES` | `scripts/router.py:114` |
| Risk tier `standard/elevated/critical` (계획서의 `normal`은 `standard`로 유지) | `router.py:36`, `apply_tier` |
| unknown 정책 (bounded lookup 1회 → 사용자 질문) | PR #27, #28 |
| `requires_code_understanding`로 L2 분기 | `apply_refinement` |
| L5 Plan(Sol/Opus)→Implement(Terra/Sonnet) | matrix `stages` |
| 결정적 Test, 로그 tail만 Fix에 전달 | `pipeline.py` `run_tests` |
| 단일 Review, FAIL→Fix→재Review→Re-plan, 상한 | `pipeline.py`, `PIPELINE_LIMITS` |
| Claude 단계별 권한 (`plan`/`read`/`edit`) | `claude_access_flags` |
| Route 재사용, Route 파일 argv/instructions 검증 | `route_reuse.py`, `validate_argv`, `validate_step_instructions` |
| Route ≠ Execution state (`state.json`) | `Pipeline.state` |

**갭 (이번 계획의 대상):**

| # | 계획서 요구 | 현재 | Phase |
|---|---|---|---|
| G1 | 모든 일반 구현이 Plan→Implement→Review | Plan은 L5 two-stage만, Review는 L4+만 (`REVIEW_MIN_LEVEL = "L4"`) | **1** |
| G2 | Skill 경로에서도 launcher가 순서 강제 | Claude `route` skill이 Agent tool로 step을 직접 실행하고 pipeline은 산문 지침 | **1** |
| G3 | TTY에서도 pipeline 강제 | `claude-route`가 TTY면 interactive 단일 hand-off (test/review 우회) | **1** |
| G4 | Read-only Inspect Fast Path (Luna Low/Haiku 단독) | 없음. `review`/`design`은 Sol/Opus 단독 | 2 |
| G5 | Trivial Edit Fast Path + gating + 결정적 검증 | L1은 단일 stage이나 gating·검증 강제 없음 | 2 |
| G6 | Classifier = Luna Low / Haiku | Luna medium / `claude-sonnet-5` medium (`model-map.json` `classifiers`) | 2 |
| G7 | L1 Codex = Luna Medium | Luna low | 2 |
| G8 | Review FAIL 시 수정 난이도 재평가 후 Fix 모델 선택 | Fix는 항상 route의 implementer | 3 |
| G9 | Review 반복 정책 (#1 Fix, #2 Fix+원인평가, 이후 Re-plan) | `review_fixes_before_replan = 1` | 3 |
| G10 | 예외적 Sol/Opus 구현 | 없음 | 3 |
| G11 | Codex/Antigravity 단계별 read-only 권한 | Claude만 강제 | 3 |
| G12 | Route는 의미 데이터만, launcher가 argv 생성 | Route가 argv 전체를 담고 검증만 함 | 4 |
| G13 | 범위 보존 (부모의 요청 확대 금지), INSPECT→MODIFY 재분류 | skill 산문에만 부분 언급 | 2 |
| G14 | 성공 지표 측정 | `eval_router_performance.py`는 분류 정확도 중심 | 4 |

**Phase 분리 이유:** 각 Phase가 단독으로 테스트·머지 가능한 동작을 낸다. Phase 2~4는 Phase 1의 실제 route/pipeline 모양에 의존하므로, Phase 1 머지 후 각각 별도 계획서로 상세화한다 (아래 “후속 Phase”).

---

## Phase 1 — 기본 워크플로우 강제 (G1, G2, G3)

### File Map

| 파일 | 책임 |
|---|---|
| `scripts/router.py` | `PLAN_MIN_LEVEL`, `REVIEW_MIN_LEVEL` 상수, `route()`의 planner stage 파생 |
| `tests/test_plan_workflow.py` (신규) | L2+ 코드 변경 route의 stage/모델/effort/review 계약 |
| `tests/test_router.py`, `test_pipeline.py`, `test_l2_refinement.py`, `test_route_reuse.py`, `test_eval_performance.py` | 새 기본값에 맞게 기대값 갱신 |
| `plugins/claude-model-effort-router/bin/claude-route` | TTY 기본 interactive 우회 제거 |
| `plugins/claude-model-effort-router/skills/route/SKILL.md`, `plugins/codex-…/skills/route/SKILL.md` | 실행을 `pipeline.py --route-file`로 |
| `references/routing-policy.md`, `README.md`, `README.ko.md` | 문서 |
| `plugins/*/scripts`, `plugins/*/config`, `plugins/*/references` | `sync_bundle.py` 산출물 (직접 편집 금지) |

시작 전: `git switch -c feat/plan-implement-review-workflow`

### Task 1: L2+ 코드 변경 route에 planner stage와 reviewer 부여

**Files:**
- Modify: `scripts/router.py:54` (`REVIEW_MIN_LEVEL`), `scripts/router.py:1129-1133` (`route()`)
- Create: `tests/test_plan_workflow.py`

**Interfaces:**
- Consumes: `router.route(...)`, `RouteResult.stages/mode/pipeline` (기존)
- Produces: `router.PLAN_MIN_LEVEL: str`; L2+ `CODE_CHANGE_TASK_TYPES` route는 `mode == "two_stage"`, `stages == [planner, implementer]` (role 키 `"planner"`, `"implementer"`), `pipeline["review"]` 항상 존재. L1 및 `design`/`review` task_type은 불변.

- [ ] **Step 1: Write the failing test**

```python
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from test_l2_refinement import routed  # noqa: E402

SOL, OPUS = "gpt-5.6-sol", "claude-opus-5"


def profile(stage):
    return stage["model"], stage["effort"]


class PlanWorkflowTests(unittest.TestCase):
    def test_l2_to_l4_code_changes_plan_with_the_judge_and_implement_cheaply(self):
        cases = (
            ("codex", "L2", {}, (SOL, "high"), ("gpt-5.6-luna", "high")),
            ("codex", "L3", {"files_touched": "2-5"}, (SOL, "high"), ("gpt-5.6-terra", "medium")),
            ("codex", "L4", {"crosses_module_boundary": "yes"}, (SOL, "high"), ("gpt-5.6-terra", "high")),
            ("claude-code", "L3", {"files_touched": "2-5"}, (OPUS, "high"), ("claude-sonnet-5", "medium")),
            ("claude-code", "L4", {"crosses_module_boundary": "yes"}, (OPUS, "high"), ("claude-sonnet-5", "high")),
        )
        for platform, level, facts, planner, implementer in cases:
            with self.subTest(platform=platform, level=level):
                result = routed(platform, understanding="yes", **facts)
                self.assertEqual((result.level, result.mode), (level, "two_stage"))
                self.assertEqual([s["role"] for s in result.stages], ["planner", "implementer"])
                self.assertEqual(profile(result.stages[0]), planner)
                self.assertEqual(profile(result.stages[1]), implementer)
                self.assertTrue(result.plan_dir)
                self.assertEqual(result.pipeline["review"]["model"], planner[0])
                self.assertEqual(result.pipeline["replan"]["model"], planner[0])

    def test_the_l2_refinement_still_picks_the_implementer_rung(self):
        codex = routed("codex", understanding="no")
        self.assertEqual(profile(codex.stages[1]), ("gpt-5.6-luna", "medium"))
        claude = routed("claude-code", understanding="no")
        self.assertEqual(claude.stages[1]["model"], "claude-haiku-4-5")

    def test_risk_tier_raises_only_the_planner_and_reviewer_effort(self):
        for platform, judge in (("codex", SOL), ("claude-code", OPUS)):
            for fact, tier, effort in (
                ({"changes_security_or_payment_logic": "yes"}, "elevated", "xhigh"),
                ({"irreversible_or_ledger_or_crypto": "yes"}, "critical", "max"),
            ):
                with self.subTest(platform=platform, tier=tier):
                    result = routed(platform, **fact)
                    self.assertEqual(result.risk_tier, tier)
                    self.assertEqual(profile(result.stages[0]), (judge, effort))
                    self.assertEqual(result.pipeline["review"]["effort"], effort)
                    self.assertNotEqual(result.stages[1]["model"], judge)

    def test_l1_and_read_only_task_types_keep_their_single_stage(self):
        l1 = routed("codex", mechanical_only="yes")
        self.assertEqual((l1.level, l1.mode, l1.pipeline["review"]), ("L1", "single", None))
        for task_type in ("design", "review"):
            with self.subTest(task_type=task_type):
                result = routed("codex", task_type, files_touched="2-5")
                self.assertEqual(result.mode, "single")
                self.assertIsNone(result.pipeline)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_plan_workflow.py -v`
Expected: FAIL — `AssertionError: 'single' != 'two_stage'` in the first two tests.

- [ ] **Step 3: Write minimal implementation**

`scripts/router.py:54` — replace the constant block:

```python
# Below these levels only the cheap implementer runs; a mechanical L1 edit needs no plan or review.
PLAN_MIN_LEVEL = "L2"
REVIEW_MIN_LEVEL = "L2"
```

`scripts/router.py` in `route()` — replace the `stages = apply_tier(...)` line with:

```python
    stages = materialise_stages(platform, raw_stages, mode, available_models)
    if mode == "single" and task_type in CODE_CHANGE_TASK_TYPES and LEVELS.index(level) >= LEVELS.index(PLAN_MIN_LEVEL):
        # The planning judge is the platform's design row; the implementer keeps its matrix/refined rung.
        planner_raw, _ = resolve_stages(matrix, "design", level)
        planner = materialise_stages(platform, planner_raw, "single", available_models)[0]
        stages = [{**planner, "role": "planner"}, {**stages[0], "role": "implementer"}]
        mode = "two_stage"
    stages = apply_tier(platform, stages, tier_profile, available_models)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_plan_workflow.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/router.py tests/test_plan_workflow.py
git commit -m "feat: route L2+ code changes through a judge plan and review"
```

### Task 2: 기존 테스트를 새 기본값에 맞춘다

프로토타입 측정: 이 변경으로 기존 테스트 약 25개가 실패한다 (전부 “L2~L4 = single stage, L4 미만 review 없음” 가정). 동작 변경이 의도이므로 구현이 아니라 기대값을 고친다. 각 수정은 “왜 바뀌는지” 한 줄을 테스트 이름/주석에 유지한다.

**Files:**
- Modify: `tests/test_router.py`, `tests/test_pipeline.py`, `tests/test_l2_refinement.py`, `tests/test_route_reuse.py`, `tests/test_eval_performance.py`, `tests/test_route_instructions.py` (실측 6개 파일, 실패 57건)
- 참고 (Task 1 결정): 계획자 (model, effort)가 구현자와 같으면 계획 단계를 넣지 않는다 — codex/claude `architectural_refactoring` L2와 Antigravity L2 전 code-change는 single 유지. 해당 route의 기대값은 single로 둔다.
- Modify (필요 시): `scripts/eval_router_performance.py` (기대 모델 계산이 `result.model`을 읽으면 `stages[-1]`로)

- [ ] **Step 1: Run the suite and list failures**

Run: `python3 -m pytest -q 2>&1 | grep -E "^(FAILED|SUBFAILED)" | sed 's/ - .*//'`
Expected: 위 5개 파일에서만 실패. 다른 파일이 실패하면 멈추고 원인을 조사한다 (의도 밖 변경).

- [ ] **Step 2: Fix by category**

| 실패 유형 | 수정 방법 |
|---|---|
| `result.model`/`result.effort`가 `None` (two_stage) | `result.stages[-1]["model"]` / `["effort"]` (구현자) 로 읽는다 |
| `mode == "single"` / `len(commands) == 1` (L2~L4) | `two_stage`, `len == 2` |
| `test_pipeline.py`의 역할 순서 `["execute", "review"]` | `["plan", "execute", "review"]`; fake 응답 리스트 맨 앞에 `{}` (plan) 추가 |
| `test_low_levels_have_no_review_and_no_replan` | L1로 변경 (L2는 이제 review 있음) |
| `test_single_stage_*_command` (L2~L4) | L1 routed 결과로 바꾸거나 `stages[-1]`로 |
| `test_claude_effort_omitted_for_haiku` | 구현자 stage(`stages[-1]`) 기준 |

- [ ] **Step 3: Run the full suite**

Run: `python3 -m pytest -q`
Expected: `347+ passed` (Task 1의 신규 4개 포함), 0 failed. `test_plugin_copies_match_the_bundle_root`는 Task 5의 sync 전까지 실패할 수 있다 — 그 한 건만 허용.

- [ ] **Step 4: Commit**

```bash
git add tests scripts/eval_router_performance.py
git commit -m "test: expect a judge plan and review for L2+ code changes"
```

### Task 3: `claude-route`가 TTY에서도 pipeline을 실행

**Files:**
- Modify: `plugins/claude-model-effort-router/bin/claude-route:22-33,58-63`

`claude -p`가 파일을 못 고친다는 기존 전제는 `acceptEdits` 도입(`claude_access_flags`)으로 사라졌다. TTY 기본값 interactive는 test/review를 우회한다. `--interactive`는 명시 opt-in으로만 남긴다 (`codex-route`와 동일).

- [ ] **Step 1: Edit** — TTY 자동 감지 제거

```bash
# `--interactive` opts into a single hand-off session that skips the test/review pipeline.
INTERACTIVE=0
while [[ "${1:-}" == "--interactive" || "${1:-}" == "--print" ]]; do
```

`if [[ -t 0 && -t 1 ]]; then INTERACTIVE=1; fi` 줄과 그 위 주석 두 줄을 삭제한다.

- [ ] **Step 2: Verify syntax** (route 생성이 분류기 CLI를 호출하므로 실행 검증은 Task 5 스모크에서 한다)

Run: `bash -n plugins/claude-model-effort-router/bin/claude-route && echo ok`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add plugins/claude-model-effort-router/bin/claude-route
git commit -m "fix: run the pipeline from claude-route on a terminal too"
```

### Task 4: Skill 실행 경로를 `pipeline.py`로 통일

**Files:**
- Modify: `plugins/claude-model-effort-router/skills/route/SKILL.md` (실행 절 1~6, “Pipeline guidance” 절)
- Modify: `plugins/codex-model-effort-router/skills/route/SKILL.md` (동일 절이 있으면)

현재 Claude skill은 부모가 Agent tool로 step을 하나씩 실행하므로 test 게이트·Review·Fix 한도·`read` 권한이 강제되지 않는다 (산문 “권장”). `CODE_CHANGE_TASK_TYPES` route는 이제 항상 two_stage+pipeline이므로 다음으로 바꾼다.

- [ ] **Step 1: 실행 절 교체** — 코드 변경 route(`pipeline` 블록 존재)는 route JSON을 임시 파일에 저장한 뒤:

```bash
python3 "${CLAUDE_SKILL_DIR}/../../scripts/pipeline.py" --route-file <route.json>
```

를 Bash로 실행하고 종료 코드/`state.json`을 사용자에게 보고한다. 사용자의 test 명령은 `MODEL_EFFORT_ROUTER_TEST_CMD`로 넘긴다 (모르면 사용자에게 한 번 묻고, 없으면 미설정 — Review 프롬프트가 “테스트 없음”을 명시한다). Agent tool 실행은 `pipeline`이 `null`인 read-only route(`design`/`review`, 이후 Phase 2의 inspect)에만 남긴다.
- [ ] **Step 2: “Pipeline guidance” 절** 을 “launcher가 강제한다”로 다시 쓰고, 산문 규칙(Opus 1회 병합 리뷰, Fix 재분류 등)은 `pipeline.py`가 이미 하는 것만 남긴다. 아직 미구현인 Fix 재분류는 Phase 3 표기.
- [ ] **Step 3: 검증** — `python3 scripts/validate_bundle.py` (skill 프런트매터/링크 검사)

Run: `python3 scripts/validate_bundle.py`
Expected: exit 0

- [ ] **Step 4: Commit**

```bash
git add plugins/*/skills/route/SKILL.md
git commit -m "docs: run code-change routes through pipeline.py from the route skill"
```

### Task 5: 동기화·문서·전체 검증

**Files:**
- Modify: `references/routing-policy.md`, `README.md`, `README.ko.md`, `SKILL.md`(번들 루트 Constraints 절)

- [ ] **Step 1: 문서 갱신** — (Task 1 재리뷰 지적: `plugins/*/references/routing-policy.md:199`, `README.md:272`의 “two-stage는 architectural_refactoring L3+ 및 L5” 서술을 “L2+ 코드 변경, 단 계획자=구현자인 행 제외”로 정정) routing-policy에 “L2+ 코드 변경 = Plan(judge)→Implement→Test→Review(judge), L1 = 단일 stage”, PLAN/REVIEW_MIN_LEVEL, `design` 행이 planner의 모델 출처라는 점을 추가. README의 “Sol은 L5에서만 계획” 류 서술을 정정.
- [ ] **Step 2: Sync and validate**

Run: `python3 scripts/sync_bundle.py && python3 scripts/validate_bundle.py && python3 -m pytest -q`
Expected: `bundle copies are in sync`, validate exit 0, 전체 통과 (parity 테스트 포함 0 failed).

- [ ] **Step 3: 실환경 스모크 (사용자 인증 필요, 자동화 불가 — 결과를 PR 본문에 기록)**

Run: `MODEL_EFFORT_ROUTER_VERBOSE=1 plugins/claude-model-effort-router/bin/claude-route -- "add a --dry-run flag to scripts/sync_bundle.py"`
Expected stderr: `phase=plan model=claude-opus-5 effort=high` → `phase=implement model=claude-…` → `phase=test`/`review model=claude-opus-5` → `phase=done`. plan 단계에서 `scripts/`를 수정하려 하면 권한 거부.

- [ ] **Step 4: Commit and open PR**

```bash
git add -A
git commit -m "docs: document the plan-implement-review workflow and sync plugin copies"
```

---

## 후속 Phase (Phase 1 머지 후 각각 별도 계획서로 상세화)

각 항목은 목표·핵심 결정·수용 기준만 확정하고, 코드 수준 단계는 Phase 1 결과(실제 route JSON 모양)를 본 뒤 작성한다.

### Phase 2 — Fast Path와 분류기 비용 (G4, G5, G6, G7, G13)
- **Inspect**: 새 `task_type = "inspect"` (분류기 프롬프트·schema·matrix 행 추가). matrix는 전 레벨 Luna Low / Haiku. `risk_tier != standard` 또는 level > L2면 router가 `review`로 승격한다 (조회가 위험 영역을 건드리면 저비용 단독 처리 금지). `pipeline` 없음, 코드 수정 access 없음(`read`).
- **Trivial Edit**: `mechanical_only=yes`이고 계획서 §3 조건을 fact로 매핑 (`files_touched=1`, crosses_* = no, `fix_or_result_known=yes`, `needs_new_structure=no`, security/API/persisted = no, `requires_code_understanding=no`, risk standard) + 결정적 검증 존재(테스트 명령 설정 또는 감지)일 때만 `mode="fast"`. 하나라도 불충족이면 Phase 1 정규 워크플로우. **unknown은 조건 충족으로 취급하지 않는다**(정규 경로로 간다 — 단 상향 재분류는 하지 않는다).
- 분류기 모델 Luna Low / Haiku, Codex L1 = Luna Medium (`config/model-map.json` + `PRIMARY_CLASSIFIER_CONFIG` 동기화).
- Route 재사용 레코드에 `operation`(inspect/modify) 저장, inspect→modify 전환은 재분류 blocker (`route_reuse.reuse_blockers`).
- 범위 보존: 분류기/skill 프롬프트에 “조회 요청을 수정으로 확대하지 않는다” 명시, 테스트로 고정.
- 수용: inspect 요청 1건이 모델 호출 1회(분류 제외)로 끝남; fast edit이 테스트 실패 시 정규 경로로 승격이 아니라 Fix 한도(2)까지 후 중단.

### Phase 3 — Fix 라우팅, 반복 정책, 예외 구현, 권한 (G8, G9, G10, G11)
- Review 출력 계약 확장: `VERDICT: FAIL` 뒤 `FIX: simple|understanding|complex|replan` 한 줄. `pipeline.py`가 파싱해 Fix 모델 선택 (simple→Luna Medium/Haiku, understanding→Luna High/Sonnet Low, complex→Terra/Sonnet High, replan→Re-plan). 라인이 없으면 route의 implementer (fail-safe, 상향 없음).
- `review_fixes_before_replan` 1→2. 두 번째 Fix 프롬프트에 “같은 원인 여부 평가” 포함, 세 번째 FAIL은 Re-plan.
- 예외적 Sol/Opus 구현: 계획서 §11의 조건을 planner가 plan JSON의 `implementation.hint = "continuous_design"` + 근거 문자열로 선언, launcher가 implementer를 Sol/Opus High로 교체(XHigh 불가, risk tier와 무관). 근거 없는 hint는 무시하고 기록.
- Codex: `codex exec --sandbox read-only|workspace-write`를 단계별로 생성하고 `validate_argv` 허용 목록에 추가 (플래그 실재 여부는 실제 `codex exec --help`로 먼저 확인). Antigravity: CLI에 권한 옵션이 없으면 한계를 문서화하고 Review 후 `git diff` 변경 감지로 대체(Plan/Review 단계에서 diff가 생기면 실패 처리).

### Phase 4 — 의미 기반 Route(schema v7)와 지표 (G12, G14)
- Route JSON에서 argv/`developer_instructions` 제거, `role/model/effort/difficulty/risk_tier`만 저장; launcher가 role별 trusted instructions·argv 생성. `SCHEMA_VERSION = 7`, v6 replay는 지원 목록에 유지. `validate_argv`/`validate_step_instructions`는 v6 경로 전용으로 축소.
- 지표: `pipeline.py`가 stage마다 `{phase, model, effort, seconds, exit}`를 `metrics.jsonl`에 기록, `scripts/eval_router_performance.py`가 Task당 모델별 호출 수·Sol/Opus 호출 수·Review 재시도·Route reuse 비율을 집계. 토큰 수는 CLI가 노출할 때만 (Codex/Claude 출력 형식 확인 후).

---

### Task 6: SessionStart 훅 정책 문구를 새 워크플로우에 맞춘다

Task 5 리뷰에서 발견: `plugins/{claude,codex}-model-effort-router/scripts/routing_policy_hook.py`의 `POLICY`가 매 세션에 주입되는데 여전히 “Agent tool로 step 위임”, “L1-L3 single-agent fast path”, “tests 후 Opus/Sol 병합 리뷰”를 지시한다. 새 워크플로우(코드 변경 route는 `pipeline.py`가 plan→implement→test→review를 강제, Agent-tool/worker 위임은 `pipeline == null` route만)와 모순이고 테스트가 그 모순을 고정하고 있다.

**Files:**
- Modify: `plugins/claude-model-effort-router/scripts/routing_policy_hook.py`, `plugins/codex-model-effort-router/scripts/routing_policy_hook.py` (`POLICY` 문자열만; 훅 파일은 플랫폼 전용이라 sync 대상 아님)
- Modify: `tests/test_claude_policy_hook.py`, `tests/test_codex_policy_hook.py`

**Requirements:**
- `POLICY`는 간결(기존 길이 수준)하고 non-blocking을 유지한다. 새 사실만 담는다: 코드 변경 route(JSON `pipeline` 블록이 non-null)는 `pipeline.py --route-file`로 실행하고 부모가 직접 구현하거나 step을 Agent tool/worker로 직접 실행하지 않는다; `pipeline`이 null인 route(design/review)만 Agent tool(Claude)/worker(Codex)로 위임; “L1-L3 single-agent fast path” 삭제(L1 코드 변경만 single-stage이며 계획/리뷰 없음); 검증·리뷰·수정 루프는 launcher가 수행하므로 “tests 후 병합 Opus/Sol 리뷰를 직접 호출” 문구 삭제. 재사용/재분류/classification-only/executor no-reroute/fallback 문구와 “Show task_type, level, model/effort, source before delegating”은 유지.
- Phase 2 이후 기능(Fast Path inspect/trivial 등)을 존재하는 것처럼 쓰지 않는다.
- 테스트는 새 문구의 실제 내용을 고정한다(`pipeline.py`, `pipeline` null 분기, fast-path 문구 부재 `assertNotIn`); 기존의 나머지 계약(non-blocking, SessionStart만, casual chat skip 등) 검증은 유지·약화 금지. Task 5 테스트 `test_code_change_workflow_is_stated_consistently_across_skills`(tests/test_router.py)가 훅에 `assertIn("single-agent fast path")`를 요구하면 훅과 skill이 일치하도록 함께 정리한다.
- 커밋: `fix: align the session policy hooks with the pipeline workflow` + blank line + `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`. 전체 pytest는 clean tree에서 0 failed.

## Task 1 결과에서 확정된 이월 사항

- 레벨 agent 프로필(`agents/level-N-*`) 지시문은 two-stage 경로에 전달되지 않는다 (L5는 원래 그랬고 이제 L2~L4도). two-stage 템플릿은 schema v6에 고정돼 있어 지금 바꾸면 저장된 route가 무효가 되므로 **Phase 4(launcher가 role별 지시문 생성)로 이월**.
- 단일 stage로 남은 계획자=구현자 행은 review도 같은 모델이다. Phase 3에서 review 모델 분리를 재검토.

## Self-Review

- **Spec coverage:** §5 워크플로우=Task 1·4; §8·13·20 Plan/Review effort=Task 1 (tier 테스트); §9·10 구현 모델=Task 1 (매트릭스 재사용, refinement 테스트); §12 Test=기존; §15·16=Phase 3; §17 권한=Claude 기존 + Phase 3; §18 재사용=Phase 2; §19 범위 보존=Phase 2; §21·22 상태=기존; §23 Route 보안=Phase 4 (현 v6 검증이 임시 방어); Fast Path 1·2·3·5·6=Phase 2; §28 지표=Phase 4. 누락 없음.
- **Placeholder scan:** Task 2의 표는 파일별 구체 패턴이며 실패 목록이 Step 1에서 확정된다(측정 근거 있음). Task 3 Step 2의 생략 사유 명시. Phase 2~4는 의도적으로 요약형 — 별도 계획서 전제.
- **Type consistency:** `PLAN_MIN_LEVEL`, `REVIEW_MIN_LEVEL`, stage role `"planner"`/`"implementer"`는 기존 `pipeline_plan`(`role: "reviewer"/"planner"`)·`result_payload` ids와 일치.
- **열린 결정 (사용자 확인 권장):** (1) risk tier 명칭을 계획서의 `normal` 대신 기존 `standard`로 유지. (2) Task 4: skill 경로를 Agent tool에서 `pipeline.py`(중첩 `claude -p`, cwd/권한은 `--permission-mode` 플래그로 제어)로 전환 — 세션의 기존 권한 설정은 상속하지 않는다. (3) L2 단순 수정에도 Sol/Opus Plan+Review 호출이 생긴다 (계획서 그대로); 비용이 과하면 Phase 2 Fast Path gating을 L2 일부로 넓히는 것으로 조정.

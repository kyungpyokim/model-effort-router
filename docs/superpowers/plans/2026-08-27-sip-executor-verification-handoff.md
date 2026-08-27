# SIP 2차 실행자 검증 핸드오프 Implementation Plan

> **에이전트 작업자용:** 구현 시 `superpowers:executing-plans`를 사용하고, 각 단계는 체크박스로 추적한다.

**목표:** SIP 1차의 `verification.recommended`를 실제 single-stage 및 two-stage 실행자 프롬프트에 전달해, 실행자가 기존 저장소 검사를 선택·실행하고 결과 또는 미실행 사유를 최종 보고하게 한다.

**구조:** `scripts/router.py`에서 이미 계산된 `verification_recommendations()`를 재사용해 실행자 전용 지침 문자열을 만든다. Codex single-stage에는 developer instructions로, Claude Code·Antigravity single-stage에는 작업 프롬프트로, two-stage에는 executor 지침으로만 넣는다. planner 프롬프트와 `command_chain_from_payload()`는 변경하지 않는다.

**기술 스택:** Python 표준 라이브러리, `unittest`, JSON, Bash launcher, 기존 bundle 동기화.

**명세:** `docs/superpowers/specs/2026-08-27-sip-verification-recommendations-design.md`

## 전역 제약

- `schema_version: 1`, `RouteResult`, 모델/추론 수준 매핑, 분류 호출 횟수를 바꾸지 않는다.
- 새 범용 테스트 러너, 저장소별 명령 설정, 자동 재시도, 결과 저장소를 추가하지 않는다.
- 실행자는 `recommended` ID만 해석한다. `skipped`는 payload 설명용이며 실행 금지 목록이 아니다.
- 실행 지침은 “기존 저장소 검사만 선택”, “미실행은 사유 보고”, “미실행 검사를 성공으로 표시하지 않음”을 명시한다.
- route-file 재생은 `verification` JSON 객체를 다시 해석하거나 새 명령을 생성하지 않는다. 저장된 stage command만 재생한다.
- 루트 `scripts/router.py`와 정책 문서를 수정하고 `python3 scripts/sync_bundle.py`로 세 플러그인 사본을 생성한다.

---

### Task 1: 실행자 지침 계약을 RED 테스트로 고정

**파일:**
- 수정: `tests/test_router.py`

**인터페이스:** `router.stage_commands(result, task)`가 생성한 실행 argv에는 추천 ID와 검증 결과 보고 규칙이 포함된다. two-stage planner argv에는 이 지침이 포함되지 않고 executor argv에만 포함된다.

- [ ] **Step 1: 세 플랫폼 single-stage RED 테스트를 추가한다.** `CommandAndLauncherTests`에 아래 테스트를 추가한다.

```python
def test_single_stage_commands_include_verification_handoff(self):
    for platform in ("codex", "claude-code", "antigravity"):
        result = routed(
            platform=platform,
            classifier=lambda _: classification("implementation", "L3"),
        )
        command_text = " ".join(router.stage_commands(result, "implement feature")[0])
        self.assertIn("focused_tests", command_text)
        self.assertIn("report", command_text)
        self.assertIn("Do not report an unrun check as passed", command_text)
```

- [ ] **Step 2: RED를 확인한다.** `python3 -m unittest tests.test_router.CommandAndLauncherTests.test_single_stage_commands_include_verification_handoff -v`를 실행한다. 현재 명령에는 검증 핸드오프 문구가 없으므로 실패해야 한다.
- [ ] **Step 3: two-stage 분리 RED 테스트를 추가한다.** 같은 클래스에 아래 테스트를 추가한다.

```python
def test_two_stage_only_executor_receives_verification_handoff(self):
    result = routed(classifier=lambda _: classification("architectural_refactoring", "L3"))
    planner, executor = router.stage_commands(result, "restructure modules")
    planner_text, executor_text = " ".join(planner), " ".join(executor)
    self.assertNotIn("focused_tests", planner_text)
    self.assertIn("focused_tests", executor_text)
    self.assertIn("plan_validation", executor_text)
    self.assertIn("Do not report an unrun check as passed", executor_text)
```

- [ ] **Step 4: RED를 확인한다.** `python3 -m unittest tests.test_router.CommandAndLauncherTests.test_two_stage_only_executor_receives_verification_handoff -v`를 실행한다. 현재 executor argv에 지침이 없어 실패해야 한다.
- [ ] **Step 5: 고위험 추천 전달 RED 테스트를 추가하고 확인한다.** 아래 테스트를 추가하고 현재 실패함을 확인한다.

```python
def test_high_risk_verification_recommendations_reach_executor(self):
    result = routed(
        classifier=lambda _: classification(
            "implementation", "L4",
            flags={
                "authentication": True,
                "data_migration": True,
                "public_api_change": True,
            },
        ),
    )
    command_text = " ".join(router.stage_commands(result, "migrate auth API")[0])
    for check_id in ("security_review", "migration_safety", "contract_review", "broad_regression"):
        self.assertIn(check_id, command_text)
```

Run: `python3 -m unittest tests.test_router.CommandAndLauncherTests.test_high_risk_verification_recommendations_reach_executor -v`

Expected: FAIL because the current command has no verification handoff text.

### Task 2: 최소 실행자 검증 핸드오프 구현

**파일:**
- 수정: `scripts/router.py`
- 테스트: `tests/test_router.py`

**인터페이스:** `verification_handoff_instructions(result: RouteResult) -> str`는 `verification_recommendations(result.task_type, result.level, result.risk_flags, result.mode)["recommended"]`만 사용해 결정적 지침 문자열을 반환한다.

- [ ] **Step 1: 순수 지침 헬퍼를 추가한다.** `verification_recommendations()` 바로 뒤에 아래 계약의 헬퍼를 둔다. 추천 ID와 사유는 기존 함수가 정한 순서를 그대로 사용한다.

```python
def verification_handoff_instructions(result: RouteResult) -> str:
    checks = verification_recommendations(
        result.task_type, result.level, result.risk_flags, result.mode,
    )["recommended"]
    check_lines = "\n".join(f"- {check['id']}: {check['reason']}" for check in checks)
    return (
        "Verification handoff:\n"
        f"Recommended checks:\n{check_lines}\n"
        "Select and run only existing repository checks that apply. "
        "Report each recommended check's result or why it was not run. "
        "Do not report an unrun check as passed."
    )
```

- [ ] **Step 2: single-stage 명령에 연결한다.** Codex `_single_stage_command()`은 기존 level instructions 뒤에 지침을 더한다. Claude Code·Antigravity `shell_command()`은 전달하는 작업 프롬프트 뒤에 지침을 더한다. 모델, effort, agent 이름, interactive 동작은 유지한다.

```python
def shell_command(result: RouteResult, task: str, interactive: bool) -> list[str]:
    task = f"{task}\n\n{verification_handoff_instructions(result)}"
    # Keep the existing platform argv construction below unchanged.

def _single_stage_command(result: RouteResult, task: str, interactive: bool) -> list[str]:
    if result.platform == "codex":
        stage = result.stages[0]
        instructions = f"{codex_agent_instructions(result.level)}\n\n{verification_handoff_instructions(result)}"
        return _codex_exec_command(stage["model"], stage["effort"], instructions, task, interactive)
    return shell_command(result, task, interactive=False)
```

- [ ] **Step 3: two-stage executor에만 연결한다.** `stage_commands()`에서 `execute_instructions`에 지침을 더한다. `instructions`와 `plan_prompt`는 변경하지 않아 planner가 검사 실행을 요구받지 않게 한다.

```python
instructions = PLANNER_INSTRUCTIONS_TEMPLATE.format(plan_path=plan_path)
execute_instructions = (
    f"{IMPLEMENTER_INSTRUCTIONS_TEMPLATE.format(plan_path=plan_path)}\n\n"
    f"{verification_handoff_instructions(result)}"
)
```
- [ ] **Step 4: 집중 GREEN을 확인한다.** Task 1의 세 테스트와 기존 `test_route_file_replays_json_commands_without_reclassification`을 실행한다.
- [ ] **Step 5: 전체 회귀를 확인한다.** `python3 -m unittest discover -s tests -v`를 실행한다.

### Task 3: 재생 경계와 사용자 문서 갱신

**파일:**
- 수정: `references/routing-policy.md`
- 수정: `README.md`
- 수정: `plugins/codex-model-effort-router/README.md`
- 수정: `plugins/codex-model-effort-router/skills/route/SKILL.md`
- 수정: `plugins/claude-model-effort-router/skills/route/SKILL.md`
- 수정: `plugins/antigravity-model-effort-router/skills/route/SKILL.md`
- 생성: `plugins/*/scripts/router.py`, `plugins/*/references/routing-policy.md`

**인터페이스:** 정책은 실행자가 추천을 보고 계약으로 처리한다는 점과 route-file의 제한을 설명한다. 세 플랫폼 skill은 실행 지침이 기존 저장소 검사를 선택하도록 요구하고, 추천 객체 자체를 새 실행 명령으로 취급하지 않는다는 점을 안내한다.

- [ ] **Step 1: 루트 정책을 갱신한다.** 실행자가 추천 ID를 검토하고 적절한 기존 검사를 실행한 뒤 결과 또는 미실행 사유를 보고해야 함을 문서화한다. Router가 명령을 선택하거나 결과를 저장하지 않는다는 경계도 유지한다.
- [ ] **Step 2: README와 세 platform skill을 갱신한다.** single/two-stage 실행자가 받는 지침, 검증 보고 의무, route-file 재생이 JSON 객체를 재해석하지 않는다는 점을 명시한다.
- [ ] **Step 3: 공유 산출물을 동기화한다.** `python3 scripts/sync_bundle.py`를 실행한다.
- [ ] **Step 4: 문서와 bundle을 검증한다.** `python3 scripts/validate_bundle.py`, `python3 -m unittest tests.test_router.BundleParityTests.test_plugin_copies_match_the_bundle_root -v`, `git diff --check`를 실행한다.

### Task 4: 최종 검증과 독립 리뷰

**파일:** Task 1-3의 변경 파일만 포함한다.

**인터페이스:** 새 라우트는 실행자에게 검증 보고를 요구하고, 기존 JSON route-file은 추가 분류·추가 명령 생성 없이 저장한 command를 재생한다.

- [ ] **Step 1: 전체 검증을 실행한다.** `python3 -m unittest discover -s tests -v`, `python3 scripts/validate_bundle.py`, `git diff --check`, `git status --short`를 실행한다.
- [ ] **Step 2: 재생 회귀를 확인한다.** `python3 -m unittest tests.test_router.CommandAndLauncherTests.test_route_file_replays_json_commands_without_reclassification tests.test_router.CommandAndLauncherTests.test_codex_launcher_replays_route_file_without_calling_codex tests.test_router.CommandAndLauncherTests.test_claude_launcher_replays_route_file_without_calling_claude -v`를 실행한다.
- [ ] **Step 3: 독립 코드 리뷰를 요청한다.** single/two-stage 지침 경계, 플랫폼 간 프롬프트 전달, route-file 재생, 문서와 생성 사본 일치만 검토한다.
- [ ] **Step 4: 커밋한다.** 모든 검증과 리뷰가 통과하면 `feat(router): hand off verification recommendations to executors`로 커밋한다.

# Probe Nudge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** test-without-change probe(`gate/probe.py`, PR #5)가 `passes_without_change`를 내면, 같은 구현 세션에 **한 번만** 되돌려서 "새 테스트가 옛 코드에서 실패하게 만들거나, 의도한 것이라면 그렇게 말하라"고 요청한다. 사람이 PR을 열기 전에 에이전트가 먼저 고치게 한다.

**Why (PR 병목):** probe는 지금 보고만 한다. 경고가 떠도 사람이 diff를 읽고 에이전트에게 다시 시키는 왕복이 남는다. 결정적 검사가 찾은 결함은 결정적 검사가 만든 증거와 함께 에이전트에게 바로 돌려주는 것이 병목을 가장 직접 줄인다. `nudge_if_unchanged`(변경이 없으면 한 번 다시 시킴)가 같은 형태의 선례다.

**Architecture:** `flow.py`의 `implement()`에서 `gate_loop → run_probe` 직후, verdict가 `passes_without_change`이면 `probe_nudge()`를 한 번 호출한다. 구현 세션을 `resume_argv`로 이어서 한 턴 돌리고, 그 턴이 파일을 바꿨을 때만 gate와 probe를 다시 돌린다. 최종 `probe`에는 nudge 기록을 덧붙인다. 새 모듈은 없다.

**Tech Stack:** 기존 Python 3, 표준 라이브러리, unittest. 새 의존성 없음.

## 동작 정의

```text
implement
  gate_loop
  run_probe                                   # verdict
  if verdict == passes_without_change and nudge 켜짐 and 세션 있음
      before = 변경 경로별 stamp
      nudge 한 턴 (구현 세션, 같은 프로필)
      after  = 변경 경로별 stamp
      if before == after                      # 아무것도 안 바꿈: 의도한 테스트로 본다
          nudge.reply = 에이전트 답변(300자), 재실행 없음
      else
          gate_loop 다시, run_probe 다시
          nudge.product_paths_added = 이번 nudge 턴이 새로 바꾼 non-test-side 경로
  review (최종 probe를 프롬프트에 사용)
```

nudge 문구(영문, 세션에 그대로 전달):

```text
The Test Gate passed, but the tests you added or changed also pass on the code before your change, so they do
not guard it. If the request is a behaviour change or a bug fix, make each new test fail on the old code (force
the failure it guards against) without changing product behaviour beyond the request. If the tests
intentionally cover behaviour that already worked, change nothing and say so in one sentence. Then stop.
```

- 탈출구("의도한 것이라면 아무것도 바꾸지 말고 한 문장으로 말하라")가 핵심이다. 기존 동작에 테스트만 추가하는 정상 요청에서 에이전트가 억지로 코드를 바꾸지 않게 한다. 어제 live에서 두 호스트가 이미 "옛 코드에서 실패시킬 수 없어서 `add()`를 바꾸지 않았다"고 스스로 보고했다. 이 동작이 nudge 이후에도 유지되는지가 v2의 성패 기준이다.
- **결과는 계속 report-only다.** nudge 후에도 `passes_without_change`가 남으면 그대로 보고하고 `status`/`exit_code`는 바꾸지 않는다.
- 사람용 출력과 `--json`에서 nudge 여부와 전후 verdict를 볼 수 있어야 한다.

## 결과 형태

`probe`에 `nudge` 키를 덧붙인다. nudge를 하지 않았으면 키가 없다(기존 결과와 byte 동일).

```python
{"verdict": "fails_without_change", ...,           # nudge 후의 최종 probe
 "nudge": {"first": "passes_without_change",       # nudge 전 verdict
           "reply": "...",                          # 에이전트 답변, 최대 300자
           "changed": True,                         # nudge 턴이 파일을 바꿨는가
           "product_paths_added": ["app/x.py"]}}    # nudge 턴이 새로 바꾼 제품 소스(비어 있으면 []).
```

- `product_paths_added`가 비어 있지 않으면 사람용 출력에 `warning: probe nudge changed product code: <paths>`를 한 줄 덧붙인다. 에이전트가 테스트를 실패시키려고 제품 동작을 바꿨을 가능성을 사람이 먼저 보게 하는 결정적 안전장치다(어제 사례처럼 정상 요청이면 `[]`).
- `calls`에 `role: "probe_nudge"`로 기록되어 `usage`에 합산된다(기존 `_sum_usage` 재사용). 이벤트는 `{"event": "probe_nudge", ...rec}`.

## Global Constraints

- **기본값은 꺼짐이다.** 측정(Task 4) 전에는 켜지 않는다. 켜는 방법: repo/user config의 `gate.probe_nudge: true`(기존 `gate.checks`와 같은 계층 규칙, repo가 user를 덮음). 측정 결과가 기준을 넘으면 기본값을 바꾸는 것은 별도 PR이다.
- nudge는 한 번뿐이다. 두 번째 nudge, probe 결과에 따른 `status` 변경, `review_fix` 이후 재probe는 하지 않는다.
- nudge가 필요한 경우는 verdict가 정확히 `passes_without_change`일 때뿐이다. `skipped`, `inconclusive`, `fails_without_change`, `probe`가 `None`(review_only/plan_only/no_changes)에서는 실행하지 않는다.
- 세션이 없거나(`self.thread` 없음) 구현 호출이 타임아웃된 경우는 건너뛴다. nudge 호출 예외는 `run_flow`의 기존 예외 처리(`status: error`)에 맡기지 않고 nudge 안에서 잡아 `probe.nudge`에 `{"error": ...}`로 기록한다. 이미 성공한 구현 결과를 nudge 실패로 `error`로 바꾸지 않는다.
- nudge 턴의 서브에이전트 정책은 `apply_review`와 같다(`n = None if implement_subagents is None else 0`). 한 턴이므로 서브에이전트를 쓰지 않는다.
- nudge 턴 이후 gate가 `failed`가 되면 기존 `gate_loop`(승격 포함)가 처리한다. 새 승격 경로를 만들지 않는다. 최종 gate가 `failed`면 probe는 기존 규칙대로 `skipped`다.
- `baseline`이 비어 있지 않거나 HEAD가 움직인 경우는 probe가 이미 `skipped`이므로 nudge도 일어나지 않는다.
- 비용: nudge가 일어난 실행은 모델 호출 1회 + (파일을 바꿨다면) gate 1회 + probe 최대 2회가 늘어난다. `passes_without_change`인 실행에서만 발생한다.
- 사용자 작업 트리 접근 규칙은 probe와 같다(probe 모듈은 수정하지 않는다). 새로 쓰는 코드는 flow의 기존 `_stamp`, `_changed_paths`, `pb.is_test_side`를 재사용한다.

## 목표 구조와 인터페이스

```text
model_effort_router/flow.py         # _Flow.probe_nudge(), implement()에서 호출, NUDGE_TEXT
model_effort_router/cli.py          # config의 gate.probe_nudge를 run_flow(probe_nudge=...)로 전달
model_effort_router/cli_display.py  # nudge 한 줄, 제품 코드 변경 경고
tests/test_mer_flow.py              # nudge 동작
tests/test_mer_cli.py               # 출력
```

```python
# flow.py
PROBE_NUDGE = ("The Test Gate passed, but the tests you added or changed also pass on the code before your change, ...")

class _Flow:
    def probe_nudge(self): ...
    # self.probe_nudge_on: run_flow(..., probe_nudge=False)에서 받는다.

def run_flow(..., probe_nudge=False): ...
```

- `probe_nudge()` 구현 순서: `before = {p: _stamp(...) for p in _changed_paths(diff)}` → 세션 한 턴(`call("probe_nudge", resume_argv(...))`) → `after` 비교 → 변경이 있으면 `gate_loop()`, `run_probe()` 다시, `product_paths_added = [p for p in 변경된 경로 if not pb.is_test_side(p)]`.
- "변경된 경로"는 stamp가 달라졌거나 새로 생긴 경로다(삭제는 stamp가 `None`이 되므로 변경으로 본다).
- `probe`가 재실행되면 `self.probe`를 최종 결과로 교체하고 `nudge` 키를 붙인다. 이벤트는 재실행한 probe에서도 기존 `probe` 이벤트 규칙을 따른다.

## Task 1: nudge 동작 (flow)

**Files:** Modify `model_effort_router/flow.py`, `tests/test_mer_flow.py`.

- [ ] 테스트 먼저 작성한다(`Harness` 사용, probe 함수는 `unittest.mock.patch`로 교체해 verdict 순서를 지정, 모델 호출은 가짜 runner가 호출 수를 센다).
  - `probe_nudge=False`(기본): `passes_without_change`여도 모델 호출 수가 늘지 않고 `probe`에 `nudge` 키가 없다(기존 결과와 동일).
  - 켜짐 + `passes_without_change`: `probe_nudge` role 호출이 정확히 1회, `probe.nudge.first == "passes_without_change"`.
  - 켜짐 + `fails_without_change`/`skipped`/`inconclusive`/`probe=None`: 호출 0회.
  - nudge 턴이 파일을 바꾸면(가짜 runner가 파일을 수정) gate와 probe가 다시 돌고 `probe.verdict`가 두 번째 결과다. 바꾸지 않으면 재실행 0회이고 `changed == False`, `reply`가 답변이다.
  - nudge 턴이 non-test-side 경로를 새로 바꾸면 `product_paths_added`에 들어가고, test-side만 바꾸면 `[]`다.
  - nudge 후 gate가 `failed`가 되면 기존 `gate_loop` 승격이 동작하고 최종 probe는 `skipped`다.
  - nudge 호출 예외는 `status`를 `error`로 바꾸지 않고 `probe.nudge.error`에 기록된다. 구현 결과(`status`, `exit_code`)는 nudge 유무와 무관하다.
  - `usage`/`calls`에 `probe_nudge` 호출이 합산된다.
- [ ] RED 확인 후 구현한다. `python3 -m unittest tests.test_mer_flow`로 GREEN을 확인한다.

## Task 2: 설정과 출력

**Files:** Modify `model_effort_router/cli.py`, `model_effort_router/cli_display.py`, `tests/test_mer_cli.py`.

- [ ] 테스트 먼저 작성한다. config `gate.probe_nudge: true`(repo, user)가 `run_flow(probe_nudge=True)`로 전달되고, 키가 없거나 `true`가 아니면 `False`다. repo가 user를 덮는다. 잘못된 타입(`"yes"` 등)은 `gate.checks`처럼 설정 오류 메시지를 낸다(기존 `_gate_checks`의 검증 방식을 따른다).
- [ ] 사람용 출력 테스트: nudge가 있으면 `probe: <최종 verdict> (nudged from passes_without_change)`, `product_paths_added`가 있으면 경고 줄. nudge가 없으면 출력이 이전과 byte 동일.
- [ ] 구현 후 `python3 -m unittest tests.test_mer_cli tests.test_mer_flow`로 GREEN을 확인한다.

## Task 3: 문서와 검증

**Files:** Modify `README.md`(`probe`/`nudge` 설명), 이 계획의 결과 절. `AGENTS.md` 포인터는 `probe.py` 한 줄이 이미 있으므로 `flow.py`의 probe 호출부 설명이 필요하면 한 줄만 추가한다.

- [ ] README에 `gate.probe_nudge` 설정, 동작, 결과의 `nudge` 필드, 기본값 꺼짐, 되돌림은 한 번뿐이며 `status`를 바꾸지 않는다는 점을 적는다.
- [ ] 전체 `python3 -m unittest discover -s tests`, `ruff check model_effort_router scripts tests evaluation`, `git diff --check`. 테스트 명령을 `tail` 등에 파이프하지 않는다(종료 코드가 가려진다).
- [ ] 변경 줄 커버리지를 stdlib trace로 측정한다. `flow.py`의 nudge 코드 80% 이상.
- [ ] 코어 변경이므로 플러그인 버전은 올리지 않는다. 머지 후 `python3 scripts/install_core.py`와 `--check`로 공용 runtime을 갱신한다.

## Task 4: live 측정 (승인 후에만)

기본값을 켤지 결정하는 근거를 만든다. 임시 저장소에서 `gate.probe_nudge: true`로 Claude·Codex 두 호스트를 돌린다(PR #5 live와 같은 `sub` 버그 저장소 형태).

| 시나리오 | 기대 |
|---|---|
| A. `sub` 버그 수정 + 그 버그를 잡는 테스트 | probe `fails_without_change`, nudge 없음 |
| B. 제품 코드는 docstring만, `add(2,3)==5` 테스트 추가 | `passes_without_change` → nudge 1회 → 에이전트가 의도했다고 답하고 아무것도 안 바꿈 (`changed == False`) |
| C. "`add`에 대한 테스트를 보강해" (모호한 요청) | nudge 후에도 제품 동작을 바꾸지 않음 |
| D. 버그 수정 요청인데 일부러 약한 테스트를 유도하는 요청("기존 `add` 테스트에 한 줄만 추가하고 sub도 고쳐라") | nudge가 테스트를 보강하게 만드는지 관찰 |

- 각 시나리오를 호스트당 3회씩 돌린다. 실행당 약 12만~22만 토큰이므로 약 12회 × 16만 ≈ 200만 토큰이다. 실행 전에 이 비용을 다시 알리고 승인을 받는다.
- 합격 기준(켜기 위한 조건): ① B·C에서 nudge 후 `product_paths_added`가 비어 있지 않은 실행이 0회. ② D에서 nudge 후 `fails_without_change`가 된 비율이 절반 이상. ③ nudge로 늘어난 토큰이 해당 실행 평균의 50% 이내.
- 기준에 못 미치면 기본값은 꺼짐을 유지하고, 측정 결과를 `docs/evaluation/`에 기록해 문구를 조정한 뒤 다시 측정한다.
- live 호출은 사용자 승인 후에만 한다(프로젝트 규칙).

## 진행 방식 (CLAUDE.md 규칙)

- `flow.py` 한 모듈과 cli·출력 변경이라 코드 크기는 작지만 에이전트가 파일을 다시 바꾸는 경로를 새로 여는 변경이다. **위험한 변경**으로 보고 구현은 `sonnet 5.5` subagent, 리뷰는 `opus 5.5` subagent(읽기 전용, 구현 대화를 잇지 않음)가 맡는다. 리뷰 지적 수정은 구현 agent를 SendMessage로 이어서 한다.
- 리뷰어에게 특히 확인시킬 항목: nudge가 정말 한 번뿐인지, `status`/`exit_code`가 nudge 유무와 무관한지, 기본값이 꺼짐일 때 기존 결과가 byte 동일한지, 탈출구 문구가 에이전트를 제품 코드 변경으로 몰지 않는지, nudge 턴이 만든 제품 코드 변경 탐지가 비는 경우(삭제·rename), nudge 후 gate 실패 경로, 예외 격리, `usage` 합산.
- 브랜치는 main에서 새로 딴다(`feat/probe-nudge`). 계획서가 먼저 커밋된다. push와 PR은 사용자 지시 후에 한다. PR 본문은 `pr` 스킬 양식의 한글.

## 완료 조건

- [ ] `gate.probe_nudge`가 꺼져 있으면 모든 결과·출력·호출 수가 이전과 같다.
- [ ] 켜져 있고 `passes_without_change`이면 구현 세션이 한 번만 되돌려지고 결과에 전후 verdict·답변·제품 코드 변경 경로가 남는다.
- [ ] nudge 턴이 아무것도 바꾸지 않으면 gate·probe 재실행이 없다.
- [ ] `status`·`exit_code`는 nudge 결과와 무관하다. nudge 실패가 구현 결과를 `error`로 바꾸지 않는다.
- [ ] 전체 테스트·ruff·opus 5.5 독립 리뷰 통과.
- [ ] live 측정(승인 후) 결과가 `docs/evaluation/`에 기록되고, 기본값 변경 여부가 합격 기준에 따라 결정된다.

## 열린 결정 (기본값으로 진행, 바꾸려면 알려주기)

1. **기본값 꺼짐:** 측정 전에는 에이전트가 제품 코드를 억지로 바꾸는 부작용을 알 수 없어서 꺼둔다. 바로 켜길 원하면 Task 4를 생략하고 기본값을 `True`로 바꾸면 되지만 권하지 않는다.
2. **한 번뿐:** 두 번째 nudge는 하지 않는다. `review_fix`가 재리뷰 없이 한 턴인 것과 같은 이유(비용 두 배, 루프 위험).
3. **`status` 불변:** `passes_without_change`가 남아도 실패로 만들지 않는다. 정상적인 "테스트만 추가" 요청이 막힐 수 있다.
4. **레벨별 차등 없음:** v2는 모든 레벨에 같은 규칙이다. 측정에서 L1 작업의 nudge 비용이 과하면 레벨 하한(`L2` 이상)을 추가한다.

# Test-Without-Change Probe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `mer run`이 끝난 뒤, 이번 실행이 추가·수정한 테스트가 **변경 이전 코드에서도 통과하는지**를 결정적으로 검사한다. 통과하면 그 테스트는 변경을 지키지 못하므로 사람이 diff를 읽기 전에 기계가 먼저 표시한다.

**Why (PR 병목):** 에이전트가 PR을 만드는 비용은 거의 0이지만 사람이 읽고 판단하는 속도는 그대로다. 지금은 "테스트가 변경 없이도 통과하는가"를 리뷰 모델의 추측(`review.py`의 `review_prompt` 문구)과 사람이 확인한다. 이 첫 검토를 결정적 검사로 옮긴다. AGENTS.md Retro 원칙("결정적으로 잡을 수 있으면 규칙 대신 검사")과 같은 방향이다.

**Architecture:** 새 모듈 `model_effort_router/gate/probe.py`가 변경 전 스냅샷(`git archive HEAD`)을 임시 디렉터리에 풀고, 이번 실행의 테스트 파일만 덮어쓴 뒤 gate가 이미 찾은 `test` 명령을 같은 방식으로 실행한다. `flow.py`는 gate 통과 직후 이 probe를 한 번 호출하고 결과를 `probe` 필드, 이벤트, 리뷰 프롬프트, 사람용 출력에 싣는다. 모델 호출은 없다.

**Tech Stack:** 기존 Python 3, 표준 라이브러리(`subprocess`, `tarfile`, `tempfile`), unittest. 새 의존성 없음.

## 동작 정의

```text
gate 통과 (test 검사 passed)
  └─ 이번 실행의 변경 경로 중 테스트 파일이 있는가?  없음 → skipped (명령 실행 0회)
       └─ 실행 전 트리가 깨끗했는가?                   아님 → skipped
            └─ 스냅샷 = HEAD 내용 + 이번 실행의 테스트 파일
                 ├─ test 명령 통과  → passes_without_change   (경고: 변경을 지키지 못함)
                 └─ test 명령 실패  → 대조 실행: 스냅샷 = HEAD 그대로
                      ├─ 대조 통과  → fails_without_change    (정상: 새 테스트가 옛 코드를 잡음)
                      └─ 대조 실패  → inconclusive            (환경 문제: 의존성 없음 등)
```

- `verdict` 값: `fails_without_change`, `passes_without_change`, `inconclusive`, `skipped`. `skipped`/`inconclusive`는 `reason` 문자열을 함께 둔다.
- **대조 실행이 필요한 이유:** `git archive`로 만든 스냅샷에는 `.venv`, `node_modules` 같은 ignored 파일이 없다. 환경 때문에 실패한 것을 "새 테스트가 옛 코드를 잡았다"로 오판하면 거짓 안심을 준다. 대조 실행이 HEAD 그대로도 실패하면 `inconclusive`로 내린다. 비용은 실패 경로(정상 경로)에서만 한 번 더 든다. 통과 경로는 대조가 필요 없다.
- **`passes_without_change`는 항상 버그가 아니다:** 기존 동작에 테스트만 추가한 PR(소스 변경 없음)도 여기에 걸린다. 그래서 v1은 **보고만 하고 `status`를 바꾸지 않는다.**

## Global Constraints

- 사용자 작업 트리를 건드리지 않는다. `git stash`, `git checkout`, `git worktree add`(`.git` 메타데이터 변경)를 쓰지 않는다. 스냅샷은 임시 디렉터리에서만 만들고 끝나면 삭제한다(실패해도 삭제).
- 실행 전 트리가 깨끗하지 않았으면(`flow.baseline`이 비어 있지 않으면) probe를 하지 않는다. HEAD 스냅샷이 사용자의 기존 미커밋 작업을 지워 엉뚱한 이유로 실패하기 때문이다. `nudge_if_unchanged`의 `was_clean` 선례와 같다.
- HEAD가 없는 저장소, git 저장소가 아닌 경로, `review_only`, `plan_only`에서는 `skipped`다.
- 실행하는 명령은 gate가 이미 실행한 `test` 명령뿐이다. 새 명령 탐색·실행 경로를 만들지 않는다. `source == "config"`이면 shell로 실행하는 기존 규칙(`discovery.Check.shell`)을 따른다.
- 타임아웃은 gate와 같은 값(`GATE_TIMEOUT_S`)을 쓴다. probe 전체 시간 상한은 최대 두 번의 실행이다.
- probe가 예외를 던져도 `mer run` 결과를 깨뜨리지 않는다. 예외는 `inconclusive` + `reason`으로 바꾼다(`run_gate`의 broken gate 처리와 같은 방식).
- 테스트가 없는 변경, gate `test`가 `not_run`/`failed`인 경우 probe는 실행하지 않는다(`skipped`).
- v1 범위 밖: 자동 재시도·에스컬레이션(probe 결과로 구현 세션을 다시 돌리기), `status` 변경, 언어별 테스트 선택 실행(변경된 테스트만 돌리기), 스냅샷에 ignored 의존성 복사, 소스 파일의 인라인 테스트(Rust `#[cfg(test)]` 등) 인식.

## 테스트 파일 판별

`probe.is_test_path(path) -> bool`. 경로 규칙만 쓴다(내용은 읽지 않는다).

| 언어 | 규칙 |
|---|---|
| Python | 파일명 `test_*.py`, `*_test.py`, 또는 경로에 `tests/` 디렉터리 + `.py` |
| JS/TS | `*.test.{js,jsx,ts,tsx,mjs,cjs}`, `*.spec.*`, `__tests__/` 아래 |
| Go | `*_test.go` |
| Ruby | `*_spec.rb`, `spec/` 아래 `.rb`, `test/` 아래 `.rb` |

판별이 어긋나도 위험은 비대칭이다. 테스트 파일을 놓치면 `skipped`(무해), 소스를 테스트로 오판하면 그 파일이 스냅샷에 새 내용으로 남아 `passes_without_change`가 나올 수 있다. 그래서 규칙은 보수적으로(오탐보다 누락) 둔다. `conftest.py`, `fixtures/`, `testdata/`는 v1에서 테스트 파일로 보지 않는다(헬퍼 변경은 소스처럼 HEAD로 되돌린다).

## 목표 구조와 인터페이스

```text
model_effort_router/gate/probe.py   # 신규
model_effort_router/flow.py         # _Flow.run_probe(), 결과 필드
model_effort_router/review.py       # review_prompt(..., probe=None)
model_effort_router/cli_display.py  # 사람용 출력 한 줄
tests/test_gate_probe.py            # 신규
tests/test_mer_flow.py              # probe 통합
```

```python
# gate/probe.py
def is_test_path(path: str) -> bool: ...
def probe_without_change(cwd, changed_paths, test_check, timeout_s, run=run_check) -> dict:
    """{"verdict", "reason", "tests": [...], "duration_s"}; never raises."""
```

- `changed_paths`는 `flow.py`의 `_changed_paths(diff)` 결과 중 이번 실행의 것(깨끗한 트리에서 시작했으므로 전체 diff와 같다).
- `test_check`는 gate 결과 `checks["test"]`(`command`, `source`)에서 `Check("test", command, source, source == "config")`로 만든다. 기존 `run_check`를 그대로 재사용하고 테스트에서는 `run`에 가짜를 주입한다.
- 스냅샷 생성: `git archive --format=tar HEAD`의 stdout을 `tarfile`로 스트림 추출(`filter="data"`를 지원하면 사용, 절대경로·`..` 멤버 거절). 이후 `changed_paths` 중 `is_test_path`인 것을 작업 트리에서 스냅샷으로 복사한다. 작업 트리에서 삭제된 테스트 파일은 스냅샷에서도 지운다.
- 소스 파일은 건드리지 않는다. 수정된 소스는 HEAD 내용이고 새로 추가된 소스는 스냅샷에 없다. 새 모듈을 import하는 새 테스트는 ImportError로 실패하며 이는 "변경 없이 실패"로 센다(새 기능 테스트의 정상 형태).

```python
# flow.py (gate_loop 직후, review 이전)
def run_probe(self):
    if self.baseline or self.gate["overall"] != "passed": → self.probe = skipped
    ...
    self.emit({"event": "probe", **self.probe})
# run_flow 결과에 "probe": flow.probe 추가 (target plan_only/review_only는 None)
```

```python
# review.py
def review_prompt(request, diff, gate, probe=None): ...
# passes_without_change일 때 프롬프트에 사실로 넣는다:
#   "Probe: the tests changed in this run PASS on the pre-change code, so they do not guard the change."
# fails_without_change: "Probe: the changed tests FAIL on the pre-change code (confirmed)."
# 그 외 verdict는 문장을 넣지 않는다.
```

사람용 출력(`cli_display.human_output`): `probe: <verdict>` 한 줄. `passes_without_change`는 `warning: changed tests also pass without the change; they may not guard it`를 덧붙인다. 기존 Door/Blast Radius 줄 아래에 둔다.

## Task 1: `gate/probe.py` — 판별·스냅샷·판정

**Files:** Create `model_effort_router/gate/probe.py`, `tests/test_gate_probe.py`.

- [ ] 테스트 먼저 작성한다. `is_test_path` 표(위 표의 경로 각각과 `conftest.py`, `src/app.py`, `docs/test_notes.md` 부정 사례).
- [ ] 임시 git 저장소(`git init`, 커밋 1개)에서 다음을 실제 파일로 검증한다. 가짜 `run`은 명령을 실행하지 않고 스냅샷 내용을 검사한다.
  - 스냅샷에서 수정된 소스는 HEAD 내용, 새 테스트 파일은 작업 트리 내용, 새로 추가한 소스 파일은 없음.
  - `run`이 통과를 반환하면 `passes_without_change`, 실패→대조 통과면 `fails_without_change`, 실패→대조 실패면 `inconclusive`. 대조 실행의 스냅샷에는 새 테스트 파일이 없어야 한다.
  - 테스트 파일이 변경에 없으면 `skipped`이고 `run` 호출 0회. HEAD 없음, 비저장소도 `skipped`.
  - `run`이 예외를 던지면 `inconclusive`. 스냅샷 임시 디렉터리는 모든 경로(성공·예외)에서 삭제된다.
  - 사용자 작업 트리는 probe 전후로 `git status --porcelain` 출력과 파일 내용이 같다.
- [ ] 실제 명령으로 한 번 검증하는 통합 테스트 1개: `python3 -m unittest`로 도는 작은 임시 프로젝트에서 (a) 변경 없이도 통과하는 테스트 → `passes_without_change`, (b) 옛 코드를 실제로 잡는 테스트 → `fails_without_change`.
- [ ] `python3 -m unittest tests.test_gate_probe`로 RED 확인 후 구현한다. 함수는 짧게 나눈다: `is_test_path`, `_extract_head(cwd, dest)`, `_overlay_tests(cwd, dest, paths)`, `probe_without_change`.
- [ ] 같은 명령으로 GREEN을 확인한다.

## Task 2: flow·review·출력 통합

**Files:** Modify `model_effort_router/flow.py`, `model_effort_router/review.py`, `model_effort_router/cli_display.py`, `tests/test_mer_flow.py`, `tests/test_mer_cli.py`, `tests/test_review.py`(있으면).

- [ ] 테스트 먼저 작성한다(`tests/test_mer_flow.py`의 `Harness` 사용; probe 함수를 `run_flow` 인수로 주입하지 말고 모듈 수준 함수를 `unittest.mock.patch`로 교체해 호출 여부·인수를 검증).
  - gate 통과 + 테스트 파일 변경 + 깨끗한 시작 → probe 호출 1회, 결과 `probe` 필드, `probe` 이벤트 1개, `status`는 probe 결과와 무관하게 불변.
  - gate `failed`/`incomplete`, 기존 dirty 트리(`baseline` 비어 있지 않음), `review_only`, `plan_only` → probe 호출 0회, 필드는 `None` 또는 `skipped`.
  - 리뷰 프롬프트: `passes_without_change`일 때만 경고 문장 포함, `fails_without_change`는 확인 문장 포함, 나머지는 기존 프롬프트와 바이트 단위로 같다(기존 테스트 보존).
  - probe 예외 시 `run_flow`가 `status`를 바꾸지 않고 `inconclusive`를 기록한다.
- [ ] `tests/test_mer_cli.py`: `human_output`이 `probe:` 줄과 `passes_without_change` 경고를 출력한다. `probe`가 없거나 `skipped`면 줄을 생략한다.
- [ ] RED 확인 후 구현한다. `run_probe()`는 `gate_loop()` 직후, 리뷰 전에 호출한다. `review_fix` 이후에는 다시 실행하지 않는다(재리뷰가 없는 기존 규칙과 같고 비용 두 배를 피한다). 이 한계를 결과 문서에 적는다.
- [ ] `python3 -m unittest tests.test_mer_flow tests.test_mer_cli tests.test_gate_probe`로 GREEN을 확인한다.

## Task 3: 문서와 검증

**Files:** Modify `AGENTS.md`(탐색 포인터 한 줄), `README.md`(`mer run` 결과 필드 설명), 이 계획의 결과 절.

- [ ] AGENTS.md "Navigation pointers"에 `Test-without-change probe: model_effort_router/gate/probe.py`를 추가한다. 새 규칙 줄은 만들지 않는다.
- [ ] README의 `mer run` 결과 설명에 `probe` 필드와 네 verdict, `passes_without_change`가 항상 버그는 아니라는 점, 보고만 하고 `status`를 바꾸지 않는다는 점을 적는다.
- [ ] 전체 `python3 -m unittest discover -s tests`, `ruff check model_effort_router scripts tests evaluation`, `git diff --check`를 실행한다. 테스트 명령을 `tail` 등에 파이프하지 않는다(종료 코드가 가려진다).
- [ ] 변경 줄 커버리지를 stdlib trace로 측정한다. `gate/probe.py`와 flow 변경 줄 80% 이상.
- [ ] 코어 변경이므로 플러그인 버전은 올리지 않는다. 머지 후 `python3 scripts/install_core.py`와 `--check`로 공용 runtime만 갱신한다.

## 진행 방식 (CLAUDE.md 규칙)

- 새 모듈과 실행 경로 변경(외부 명령 실행)이므로 **큰/위험한 변경**에 해당한다. 구현은 `sonnet 5.5` subagent, 리뷰는 `opus 5.5` subagent(읽기 전용, 구현 대화를 잇지 않음)가 맡는다. 리뷰 지적 수정은 구현 agent를 SendMessage로 이어서 한다.
- 리뷰어에게 특히 확인시킬 항목: 사용자 트리 불변, tar 추출 경로 안전, 임시 디렉터리 정리, 대조 실행 논리(거짓 안심 경로가 남는지), 예외 격리, 기존 프롬프트 바이트 동일.
- 브랜치는 main에서 새로 딴다(`feat/test-without-change-probe`). 커밋·push·PR은 사용자 지시 후에 한다. PR 본문은 한글.
- **live 검증은 사용자 승인 후에만 한다.** 승인 시 시나리오: 임시 저장소에서 (a) 버그를 실제로 잡는 테스트를 추가하게 하는 요청 → `fails_without_change`, (b) 기존 동작에 대한 테스트만 추가하게 하는 요청 → `passes_without_change`. Claude·Codex 두 호스트에서 실행한다.

## 완료 조건

- [ ] 테스트 파일이 변경에 있고 gate가 통과한 `mer run`이 `probe` verdict를 반환한다.
- [ ] 변경 없이 통과하는 테스트는 `passes_without_change`, 옛 코드를 잡는 테스트는 `fails_without_change`로 구분된다(실제 `unittest` 통합 테스트로 입증).
- [ ] 환경 문제로 실패한 경우 `inconclusive`이며 "정상"으로 보이지 않는다(대조 실행 테스트).
- [ ] 사용자 작업 트리·`.git`이 probe 전후 동일하고 임시 디렉터리가 남지 않는다.
- [ ] dirty 시작, 테스트 파일 없음, gate 비통과, `review_only`/`plan_only`에서 명령 실행 0회.
- [ ] `status`·`exit_code`는 probe 결과로 바뀌지 않는다. 기존 테스트가 모두 통과한다.
- [ ] opus 5.5 독립 리뷰에서 CRITICAL/HIGH가 해결된다.

## 열린 결정 (기본값으로 진행, 바꾸려면 알려주기)

1. **보고만 vs 차단:** 기본은 보고만. `passes_without_change`일 때 구현 세션에 한 번 되돌리는 nudge(`nudge_if_unchanged`와 같은 형태)는 v2로 미룬다. 정상적인 "테스트만 추가" PR을 막을 수 있어서다.
2. **끄는 방법:** 기본은 테스트 파일이 바뀐 실행에서만 동작하므로 비용이 이미 제한된다. `--no-probe` 플래그는 만들지 않는다. 느린 스위트에서 불만이 생기면 추가한다.
3. **dirty 트리:** v1은 건너뛴다. 이후 기존 dirty 파일을 스냅샷에 함께 덮어쓰는 방식으로 확장할 수 있다.

# Shared Core Plugin Inheritance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 이미 한 번 설치해 공유하는 `model_effort_router` 코어에 최소 부모 진입점 클래스를 추가하고, 각 플러그인이 호스트 설정만 가진 자식 클래스로 CLI·gate·hook을 연결한다.

**Architecture:** `model_effort_router.entrypoints.ModelEffortRouter`는 기존 함수형 entrypoint를 호출하는 얇은 facade다. 실제 분류·실행은 현재의 `cli.py` → `policy.router` → `flow.run_flow`와 `host.hosts.Host` 전략을 그대로 사용한다. 각 플러그인의 `router.py`는 `host`, `gate_host`, `runtime_api`만 선언하며, 기존 보안 bootstrap과 공유 runtime 설치 계약은 유지한다.

**Tech Stack:** Python 3 표준 라이브러리, `unittest`, subprocess 격리 테스트, 기존 `scripts/install_core.py`. 새 제품 의존성 없음.

**Spec:** `docs/plans/2026-10-06-single-shared-core-plan.md`의 완료된 단일 runtime 계약과 사용자 요구 “공용 `model_effort_router` 부모 클래스를 plugins가 상속해 연결”.

## Global Constraints

- 이 계획은 후속 구조 변경이다. 기존 shared-core 계획에서 완료한 코어 사본 삭제, 사용자당 runtime 1개, `scripts/install_core.py`, `MER_CORE_PATH` override는 다시 구현하지 않는다.
- `model_effort_router/`가 runtime 코드의 단일 소스다. 플러그인에는 host integration, manifest, hooks, skills, launcher와 작은 자식 클래스만 둔다.
- 부모 클래스는 entrypoint facade다. `classify()`나 `execute()`를 새로 만들거나 기존 route/flow 로직을 클래스로 옮기지 않는다.
- `model_effort_router.host.hosts.Host` namedtuple과 `HOSTS` registry는 이미 adapter/executor 전략 경계다. 이를 새 class hierarchy로 교체하지 않는다.
- `cli._main()`의 `hosts.get(args.host, env)`, hook의 `hosts.get(env=env)`, `flow.run_flow(..., host=CODEX)` 기본 동작과 `--host` override를 보존한다.
- Codex/Claude gate는 플러그인 host를 설정한다. Antigravity `bin/mer-gate`는 계속 `gate(host=None)`를 호출해 기존 `MER_HOST`를 보존한다.
- `RUNTIME_API = 1`을 유지한다. 새 class는 additive API다. 기존 함수형 launcher는 새 코어에서 계속 동작해야 한다.
- 새 launcher가 class가 없는 이전 API 1 코어를 만났을 때 traceback 없이 CLI/gate는 stderr 안내와 2, hook은 무출력 0으로 종료해야 한다.
- launcher의 절대 runtime 검사, cwd/PYTHONPATH shadow 차단, package/bootstrap symlink 거절, `-I` 격리 동작을 보존한다.
- hook의 `except BaseException` fail-open, 무출력, 종료 코드 0 계약과 실제 plugin root 전달을 보존한다.
- `scripts/install_core.py`의 staging, rollback, 전체 package 교체와 `--check`는 변경하지 않는다. 설치 artifact 검증은 임시 디렉터리에서만 한다.
- `pyproject.toml`, pip/site-packages 전환, 제3자 plugin registry/discovery, executor/adapter 이동은 범위 밖이다. 표준 패키지 배포 요구가 생길 때 별도 계획으로 다룬다.
- 구현 시 tests-first로 진행하고 변경 모듈 coverage 80% 이상, 전체 테스트, 독립 리뷰를 완료한다.

## 목표 구조

```text
model-effort-router/
├── model_effort_router/
│   ├── entrypoints.py                  # ModelEffortRouter facade + 기존 함수 API
│   ├── cli.py                          # 기존 host 선택·route·run 흐름
│   ├── flow.py                         # 기존 실행/Test Gate/review 흐름
│   └── host/hosts.py                   # 기존 Host namedtuple 전략
├── plugins/
│   ├── codex-model-effort-router/
│   │   ├── router.py                   # CodexRouter(ModelEffortRouter)
│   │   ├── bin/{mer,mer-gate}
│   │   └── hooks/user_prompt_submit.py
│   ├── claude-model-effort-router/
│   │   ├── router.py                   # ClaudeRouter(ModelEffortRouter)
│   │   ├── bin/{mer,mer-gate}
│   │   └── hooks/user_prompt_submit.py
│   └── antigravity-model-effort-router/
│       ├── router.py                   # AntigravityRouter(ModelEffortRouter)
│       └── bin/{mer,mer-gate}
└── scripts/install_core.py             # 기존 공유 runtime 설치기
```

## Task 1: 부모 entrypoint facade 계약

**Files:**
- Modify: `model_effort_router/entrypoints.py:7-54`
- Modify: `tests/test_entrypoints.py`

**Interfaces:**
- Consumes: 기존 `cli(host, *, runtime_api=1)`, `gate(host=None, *, runtime_api=1)`, `hook(host, plugin_root, *, runtime_api=1)`.
- Produces: `ModelEffortRouter` class와 class attributes `host`, `gate_host`, `runtime_api`; classmethods `run_cli()`, `run_gate()`, `run_hook(plugin_root)`.
- Compatibility: 기존 세 함수와 `RUNTIME_API = 1`은 이름·인수·동작을 그대로 유지한다.

- [x] **Step 1: 자식 클래스 위임 테스트를 먼저 작성한다**

```python
class ExampleRouter(entrypoints.ModelEffortRouter):
    host = "claude"
    gate_host = "claude"
    runtime_api = 1

with patch.object(entrypoints, "cli", return_value=7) as call:
    self.assertEqual(ExampleRouter.run_cli(), 7)
    call.assert_called_once_with("claude", runtime_api=1)

with patch.object(entrypoints, "gate", return_value=3) as call:
    self.assertEqual(ExampleRouter.run_gate(), 3)
    call.assert_called_once_with("claude", runtime_api=1)

root = Path("/tmp/plugin")
with patch.object(entrypoints, "hook", return_value=5) as call:
    self.assertEqual(ExampleRouter.run_hook(root), 5)
    call.assert_called_once_with("claude", root, runtime_api=1)
```

- [x] **Step 2: Antigravity gate의 `None` 전달 테스트를 작성한다**

```python
class AntigravityRouter(entrypoints.ModelEffortRouter):
    host = "antigravity"
    gate_host = None
    runtime_api = 1

with patch.object(entrypoints, "gate", return_value=4) as call:
    self.assertEqual(AntigravityRouter.run_gate(), 4)
    call.assert_called_once_with(None, runtime_api=1)
```

- [x] **Step 3: RED를 확인한다**

Run: `python3 -m unittest tests.test_entrypoints -v`

Expected: `AttributeError: module 'model_effort_router.entrypoints' has no attribute 'ModelEffortRouter'`.

- [x] **Step 4: 최소 facade를 구현한다**

```python
class ModelEffortRouter:
    """Plugin host settings over the stable function entrypoints."""

    host = None
    gate_host = None
    runtime_api = None

    @classmethod
    def run_cli(cls):
        return cli(cls.host, runtime_api=cls.runtime_api)

    @classmethod
    def run_gate(cls):
        return gate(cls.gate_host, runtime_api=cls.runtime_api)

    @classmethod
    def run_hook(cls, plugin_root):
        return hook(cls.host, plugin_root, runtime_api=cls.runtime_api)
```

이 class는 기존 함수 아래에 둔다. ABC, factory, registry, instance lifecycle을 추가하지 않는다. `_check_api()`와 hook fail-open은 기존 함수가 계속 담당한다.

- [x] **Step 5: 신규·기존 entrypoint 테스트를 통과시킨다**

Run: `python3 -m unittest tests.test_entrypoints -v`

Expected: 기존 함수 API mismatch/환경변수/hook fail-open 테스트와 새 class 위임 테스트가 모두 PASS.

## Task 2: 플러그인 자식 클래스와 launcher 연결

**Files:**
- Create: `plugins/codex-model-effort-router/router.py`
- Create: `plugins/claude-model-effort-router/router.py`
- Create: `plugins/antigravity-model-effort-router/router.py`
- Modify: `plugins/{codex,claude,antigravity}-model-effort-router/bin/mer`
- Modify: `plugins/{codex,claude,antigravity}-model-effort-router/bin/mer-gate`
- Modify: `plugins/{codex,claude}-model-effort-router/hooks/user_prompt_submit.py`
- Modify: `tests/test_plugin_bundle.py`

**Interfaces:**
- Consumes: Task 1의 `ModelEffortRouter`와 기존 launcher bootstrap.
- Produces: `CodexRouter`, `ClaudeRouter`, `AntigravityRouter`; 각 launcher는 해당 class의 `run_cli`, `run_gate`, `run_hook`만 호출한다.
- Security boundary: 공유 runtime 검증 후 `importlib.util.spec_from_file_location()`으로 실제 plugin root의 `router.py`를 명시적으로 읽는다. plugin root를 `sys.path`에 추가하거나 bare `from router`를 사용하지 않는다.

- [x] **Step 1: bundle stub을 class API로 바꾸고 연결 테스트를 RED로 만든다**

`tests/test_plugin_bundle.py`의 임시 `entrypoints.py` stub은 `RUNTIME_API = 1`, `ModelEffortRouter`, 세 classmethod와 `report()`만 제공한다. 기존 `cli/gate/hook` 함수는 이 fixture에 두지 않는다. classmethod는 `[entrypoints.__file__, operation, host, runtime_api, plugin_root?]`를 직접 출력한다. 세 plugin의 CLI/gate/hook 기대값은 현재 함수 호출과 동일해야 한다.

```python
expected = {
    "bin/mer": ["cli", host, 1],
    "bin/mer-gate": ["gate", None if host == "antigravity" else host, 1],
    "hooks/user_prompt_submit.py": ["hook", host, str(plugin), 1],
}
```

현재 함수형 loader는 class-only stub의 `entrypoints.cli/gate/hook`을 찾지 못하므로 이 테스트가 실제 RED가 된다. 구현 후에는 plugin `router.py`의 자식 class가 stub의 `ModelEffortRouter`를 상속해 GREEN이 된다.

- [x] **Step 2: 이전 API 1 runtime과 plugin class 파일 실패를 테스트한다**

임시 runtime의 `entrypoints.py`에 `RUNTIME_API = 1`과 기존 `cli/gate/hook`만 두고 `ModelEffortRouter`는 두지 않는다.

- 기존 함수형 launcher를 직접 흉내 낸 호출은 새 코어의 함수 API에서 계속 성공해야 한다.
- 새 plugin CLI/gate는 class import 실패를 잡아 stderr에 “shared core unavailable or incompatible”를 출력하고 2를 반환해야 한다.
- 새 plugin hook은 stdout/stderr 없이 0을 반환해야 한다.

별도 fixture이므로 Step 1의 class-only stub에 기존 함수를 섞지 않는다.

각 plugin 복사본에서 `router.py`를 차례로 삭제하고, syntax error 내용으로 바꾸고, 외부 파일을 가리키는 symlink로 바꾼다. CLI/gate는 세 경우 모두 traceback 없이 stderr 안내와 2, hook은 무출력 0이어야 한다. 각 subtest 뒤에는 원본 `router.py`를 복원해 다음 plugin 검증을 격리한다.

- [x] **Step 3: RED를 확인한다**

Run: `python3 -m unittest tests.test_plugin_bundle.PluginBundleTest.test_all_loaders_import_one_shared_core_and_forward_arguments tests.test_plugin_bundle.PluginBundleTest.test_missing_corrupt_relative_and_incompatible_core_fail_safely -v`

Expected: class-only stub에는 `cli/gate/hook` 함수가 없으므로 현재 loader가 FAIL. 테스트 자체는 새 loader의 class 호출 결과를 기대한다.

- [x] **Step 4: host 설정만 가진 자식 클래스를 만든다**

```python
# plugins/codex-model-effort-router/router.py
from model_effort_router.entrypoints import ModelEffortRouter


class CodexRouter(ModelEffortRouter):
    host = "codex"
    gate_host = "codex"
    runtime_api = 1
```

Claude는 class/host 이름을 `ClaudeRouter`/`claude`로 바꾼다. Antigravity는 `AntigravityRouter`, `host = "antigravity"`, `gate_host = None`, `runtime_api = 1`로 둔다. 차이는 선언값뿐이며 executor/adapter 메서드를 override하지 않는다.

- [x] **Step 5: launcher의 마지막 연결만 자식 class로 교체한다**

기존 runtime 절대경로·symlink·bootstrap 파일 검사와 `entrypoints.RUNTIME_API != 1` guard를 그대로 둔다. 검사 뒤 plugin root의 `router.py`가 일반 파일이며 symlink가 아닌지 확인하고, 그 정확한 경로를 표준 라이브러리로 load한다. spec 생성, module 실행, class 조회도 현재 CLI/gate의 `except Exception` 또는 hook의 `except BaseException` 범위 안에 둔다.

```python
import importlib.util

plugin_root = Path(__file__).resolve().parent.parent
router_path = plugin_root / "router.py"
if router_path.is_symlink() or not router_path.is_file():
    raise ImportError("plugin router missing")
spec = importlib.util.spec_from_file_location("_mer_codex_router", router_path)
if spec is None or spec.loader is None:
    raise ImportError("plugin router unavailable")
plugin_router = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin_router)
CodexRouter = plugin_router.CodexRouter

sys.exit(CodexRouter.run_cli())
```

Claude와 Antigravity는 module name과 class name만 해당 host 이름으로 바꾼다. 공통 loader helper나 동적 host discovery는 추가하지 않는다.

`bin/mer-gate`는 `CodexRouter.run_gate()`/`ClaudeRouter.run_gate()`/`AntigravityRouter.run_gate()`를 호출한다. hook은 계산한 `plugin_root`를 `run_hook(plugin_root)`에 넘긴다. plugin root를 공유 core 경로로 대체하지 않는다.

- [x] **Step 6: loader와 실제 설치 artifact 회귀를 통과시킨다**

Run: `python3 -m unittest tests.test_plugin_bundle tests.test_entrypoints tests.test_user_prompt_submit tests.test_gate_cli -v`

Expected: 동일 runtime `entrypoints.__file__`, host 전달, Antigravity gate 환경 보존, missing/corrupt/relative/old-core/API mismatch 실패, cwd shadow 차단, core symlink 거절, plugin `router.py` missing/corrupt/symlink 안전 실패, hook fail-open이 모두 PASS.

## Task 3: 설치 계약과 구조 문서 정렬

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `plugins/codex-model-effort-router/README.md`
- Modify: `plugins/claude-model-effort-router/README.md`
- Modify: `plugins/antigravity-model-effort-router/README.md`

**Interfaces:**
- Consumes: Task 2의 최종 tree와 기존 `scripts/install_core.py` 명령.
- Produces: 단일 설치와 상속 연결을 구분한 운영·개발 문서.

- [x] **Step 1: root 구조 설명을 실제 파일에 맞춘다**

`README.md`의 구조 표에 `entrypoints.ModelEffortRouter`가 함수 API를 감싸는 facade이고 `plugins/*/router.py`가 host 값만 선언한다고 기록한다. 다음 설치 명령은 바꾸지 않는다.

```bash
python3 scripts/install_core.py
python3 scripts/install_core.py --check
MER_CORE_PATH="$PWD" python3 plugins/codex-model-effort-router/bin/mer run --help
```

- [x] **Step 2: 유지보수 navigation을 갱신한다**

`AGENTS.md` navigation pointers에 아래 두 줄을 추가한다.

```text
- Plugin entrypoint facade: `model_effort_router/entrypoints.py`
- Host declarations: `plugins/*-model-effort-router/router.py`
```

- [x] **Step 3: 세 plugin README에 같은 설치 의미를 짧게 반영한다**

각 README의 기존 shared-runtime 설치 절차 옆에 “plugin의 `router.py`는 설치된 core의 `ModelEffortRouter`를 상속하고 해당 host만 선택한다”는 한 문장을 추가한다. pip 설치, 자동 core update, plugin-local fallback을 암시하는 문구는 넣지 않는다.

- [x] **Step 4: 구현된 코어를 설치하고 문서 명령을 검증한다**

Run: `python3 scripts/install_core.py && python3 scripts/install_core.py --check`

Expected: shared runtime 설치가 성공하고 `--check`가 `in sync`와 종료 코드 0을 반환한다. 이 설치는 계획 작성 중에는 실행하지 않고, 향후 구현이 끝난 뒤 AGENTS.md 계약에 따라 실행한다. 문서의 파일 경로는 `test -f`로 모두 확인한다.

## Task 4: 전체 검증과 독립 리뷰

**Files:**
- Verify only: 위 Task들의 변경 파일

**Interfaces:**
- Consumes: Task 1~3의 facade, plugin subclasses, 문서.
- Produces: 설치 artifact·회귀·coverage·review 증거.

- [x] **Step 1: 전체 테스트를 실행한다**

Run: `MER_CORE_PATH="$PWD" python3 -m unittest discover -s tests`

Expected: 모든 테스트 PASS. 테스트는 임시 runtime만 설치하며 실제 사용자 runtime을 바꾸지 않는다.

- [x] **Step 2: 변경 모듈 coverage를 측정한다**

Run: `python3 -m coverage run --source=model_effort_router.entrypoints -m unittest tests.test_entrypoints tests.test_plugin_bundle tests.test_user_prompt_submit tests.test_gate_cli && python3 -m coverage report --include='*/model_effort_router/entrypoints.py'`

Expected: `entrypoints.py` line coverage 80% 이상. `coverage`가 환경에 없으면 raw `trace` 결과로 대체하지 않는다. 검증 환경에 coverage 개발 도구를 준비한 뒤 같은 명령을 실행하고 수치가 확인될 때까지 완료 처리하지 않는다. 제품 runtime dependency에는 추가하지 않는다.

- [x] **Step 3: 공유 설치 artifact smoke를 실행한다**

임시 HOME/MER_CORE_PATH에 `scripts.install_core.install()`로 코어를 한 번 설치하고, 복사한 세 plugin을 `sys.executable -I`로 실행한다. 원본 checkout을 cwd/PYTHONPATH로 제공하지 않는다.

Expected: Codex/Claude dry-run과 gate, Antigravity chat dry-run과 gate, Codex/Claude hook이 Task 2의 host 계약대로 성공한다. `git ls-files 'plugins/*/model_effort_router/*'`는 비어 있어야 한다.

- [x] **Step 4: 정적 검사를 실행한다**

Run: `git diff --check && python3 -m compileall -q model_effort_router plugins`

Expected: whitespace와 syntax 오류 없음.

- [x] **Step 5: 독립 로컬 리뷰를 실행하고 CRITICAL/HIGH를 해결한다**

`code-reviewer`, `python-reviewer`, `security-reviewer` agent에 현재 diff를 각각 검토시킨다. 리뷰 범위는 class facade가 route/flow를 복제하지 않는지, old/new core 호환 방향, Antigravity gate `None`, 명시적 plugin file load, cwd/symlink 방어, hook 무출력 0이다. CRITICAL/HIGH finding은 같은 범위 안에서 수정하고 관련 테스트와 전체 suite를 다시 실행한다.

- [x] **Step 6: 최종 diff를 검토한다**

Run: `git status --short && git diff --stat && git diff --check`

계획 밖 파일과 기존 사용자 변경이 섞이지 않았는지 확인한다. 커밋·push는 사용자가 별도로 요청할 때만 수행한다.

## Risks & Mitigations

- **Risk:** 부모 class를 실제 router 엔진으로 오해해 route/flow를 중복 구현한다.
  - **Mitigation:** classmethod 세 개는 기존 함수에만 위임하고 Host namedtuple과 CLI/flow를 유지한다.
- **Risk:** API 1인 이전 core에는 class가 없어 새 plugin이 import traceback을 낸다.
  - **Mitigation:** 자식 class import를 기존 launcher 보호 블록 안에 두고 old-core fixture로 종료 계약을 고정한다.
- **Risk:** Antigravity gate가 자식 host를 강제로 설정해 기존 환경 선택을 바꾼다.
  - **Mitigation:** `gate_host = None`을 명시하고 stub/실제 artifact 양쪽에서 검증한다.
- **Risk:** plugin root import 추가가 cwd/PYTHONPATH shadow 방어를 약화한다.
  - **Mitigation:** `sys.path`에 plugin root를 추가하지 않고 검증한 `plugin_root/router.py`를 경로로 직접 load하며 malicious-cwd와 router symlink 테스트를 유지한다.
- **Risk:** shared runtime과 plugin 배포 시점이 달라진다.
  - **Mitigation:** 함수 API와 `RUNTIME_API = 1`을 유지하고, 새 plugin/old core 실패를 안내형으로 만든다. 자동 설치나 fallback은 추가하지 않는다.

## Success Criteria

- [x] `model_effort_router.entrypoints.ModelEffortRouter`는 기존 함수 API에만 위임하는 facade다.
- [x] 세 plugin은 각각 한 자식 class로 host/gate_host/runtime_api만 선언한다.
- [x] 실제 classify/execute, adapter, executor, Host registry에는 중복 class hierarchy가 생기지 않는다.
- [x] old plugin/new core는 함수 API로 동작하고 new plugin/old API 1 core는 안전하게 실패한다.
- [x] Codex/Claude gate는 host를 고정하고 Antigravity gate는 기존 환경을 보존한다.
- [x] `scripts/install_core.py`, `MER_CORE_PATH`, runtime 1개 설치와 `--check` 계약이 유지된다.
- [x] cwd/PYTHONPATH shadow, symlink, API mismatch, incomplete core 방어가 유지된다.
- [x] hook은 모든 bootstrap/runtime 실패에서 무출력 0으로 fail-open한다.
- [x] 전체 tests PASS, 변경 모듈 coverage 80% 이상, `git diff --check` PASS, 독립 리뷰 CRITICAL/HIGH 0건이다.

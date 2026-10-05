# Single Shared Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 세 플러그인의 `model_effort_router/` 구현 사본을 모두 삭제하고, 한 곳의 공유 코어를 import하며 원본 내부의 실질 중복도 정리한다.

**Architecture:** 저장소의 `model_effort_router/`가 유일한 코어 소스다. 명시적인 표준 라이브러리 설치 명령으로 사용자 공용 경로에 코어를 한 번 설치한다. 세 플러그인은 manifest, skill, hook 설정과 얇은 실행 로더만 가지고 동일한 공유 코어를 import한다.

**Tech Stack:** 기존 Python 3, 표준 라이브러리, unittest, subprocess 격리 테스트. 새 제품 의존성 없음.

**Spec:** 사용자 요구: `cli.py`, `entrypoints.py`, `flow.py`, `review.py`를 포함한 코어 구현의 4벌 중복 제거 및 중복 감사에서 확인한 공통 로직 재사용. 이 문서의 완료 조건이 이전 `2026-10-05-shared-plugin-entrypoints-plan.md`의 사본 유지 조건을 대체한다.

## Global Constraints

- 사용자의 `commit 하고 진행해` 승인으로 계획을 커밋하고 구현을 진행했다. 사용자 실제 runtime 설치는 하지 않으며 설치 검증은 임시 디렉터리에서만 수행한다.
- 구현은 기존 `codex/shared-plugin-entrypoints`에서 이어간다. main 기반 브랜치와 PR #2가 이미 있으므로 추가 브랜치/PR를 만들지 않는다.
- 저장소 코어는 기존 `model_effort_router/`에 유지한다. 세 플러그인 안에는 코어 구현 파일이 0개여야 한다.
- 사용자 공용 runtime은 세 호스트가 공유하는 한 설치다. 호스트별 runtime, plugin-local fallback, symlink, 실행 중 자동 다운로드/설치는 만들지 않는다.
- 현재의 플러그인 단독 독립 실행 계약을 공유 runtime 사전 설치 계약으로 변경한다. 설치 안내·테스트에 이 변화를 명시한다.
- `--host` 우선순위, gate의 Antigravity 환경 보존, hook 무출력/0 종료, 재귀 방지, 출력 형식·종료 코드·호스트별 기능 제한을 보존한다.
- hook에 전달하는 `plugin_root`는 실제 플러그인 경로다. 현재 실제 사용처는 host/codex_hooks.py의 advice 명령 문자열 생성이다. 공유 코어 경로로 바꾸지 않는다.
- 로더의 import 경로는 사용자 공용 경로 또는 명시한 `MER_CORE_PATH`만 쓴다. cwd, 프로젝트 설정, 부모 폴더 탐색으로 코어를 찾지 않는다.
- 코어 변경 시 번들을 동기화하라는 현 AGENTS.md 규칙은 Task 2에서 새 단일 코어 계약으로 교체한다. 그 전에는 현 규칙이 유효하다.

## 목표 구조와 설치 계약

```text
repository/
├── model_effort_router/              # 유일한 소스 구현
├── scripts/install_core.py           # 공용 runtime 설치/갱신/검사
└── plugins/{codex,claude,antigravity}-model-effort-router/
    ├── bin/{mer,mer-gate}            # 공용 경로 설정 후 import
    ├── hooks/                       # 지원 호스트의 최소 로더·설정
    ├── skills/
    └── host-specific manifest

${XDG_DATA_HOME:-~/.local/share}/model-effort-router/runtime/
└── model_effort_router/              # 사용자당 공유 설치 1개
```

- 설치: 먼저 `git clone https://github.com/kyungpyokim/model-effort-router-next.git`로 별도 checkout을 준비하고 그 디렉터리에서 `python3 scripts/install_core.py`를 실행한다. marketplace 플러그인만 설치해서는 코어 준비를 완료할 수 없다는 점을 각 README에 명시한다. PyPI 배포나 installer 자체를 플러그인에 복제하는 경로는 만들지 않는다.
- 재설치/갱신: checkout을 대상 릴리스로 갱신한 후 동일 명령. 플러그인 업데이트는 공유 코어를 자동 업데이트하지 않는다. 삭제된 원본 모듈이 runtime에 남지 않도록 전체 package를 교체한다.
- 검사: `python3 scripts/install_core.py --check`; 대상과 원본의 파일 목록/내용 차이는 종료 코드 1, 동일하면 0.
- 개발/테스트 override: `MER_CORE_PATH=/absolute/path/to/repository` 또는 임시 runtime 부모. 그 아래에 `model_effort_router/`가 있어야 한다. 상대 경로는 거절한다.
- 기본 runtime 탐색: `${XDG_DATA_HOME:-~/.local/share}/model-effort-router/runtime`. 상대 XDG_DATA_HOME은 기본 경로로 처리한다.
- import 전에 `runtime/model_effort_router/entrypoints.py` 존재를 검사해서 전역 site-packages로 우연히 fallback하지 않게 한다. runtime 없음/불완전/호환 API 불일치: CLI·gate는 stderr에 공유 코어 준비 필요와 문서 경로를 안내하고 종료 코드 2. hook은 stdout/stderr 없이 0.
- 호환성은 배포 버전 문자열이 아니라 정수 `RUNTIME_API = 1`로 관리한다. 로더는 `cli(host, *, runtime_api=1)`, `gate(host=None, *, runtime_api=1)`, `hook(host, plugin_root, *, runtime_api=1)`를 사용한다. 기존 함수 직접 호출은 기본값으로 유지한다. 호환되지 않는 변경 시에만 API 정수를 올린다. 공용 runtime은 한 개이므로 서로 다른 API 버전의 플러그인 동시 사용은 지원하지 않는다. API를 바꾸는 릴리스는 세 플러그인과 runtime을 함께 업데이트하는 계약이며, 이전 플러그인을 계속 실행해야 한다면 이전 릴리스 runtime으로 되돌린다. 동일 API 안에서는 배포 버전이 달라도 위 인터페이스를 보존한다.
- 설치기는 표준 라이브러리로 staging 디렉터리를 같은 부모에 준비한다. 복사 검증 후 기존 디렉터리를 backup으로 rename하고 staging을 교체한다. 교체 실패 시 기존 runtime을 복원하고 nonzero 종료한다. staging/backup 잔여물은 설치기가 정리한다. 실행 중 갱신의 완전 무중단 지원은 범위 밖이며 갱신 후 호스트 재시작을 안내한다.

## Task 1: 공유 코어 설치와 진입점 호환성

**Files:** Create `scripts/install_core.py`, `tests/test_core_install.py`; Modify `model_effort_router/entrypoints.py`, `tests/test_entrypoints.py`.

**Interfaces:** installer `install(source: Path, runtime: Path) -> None`, `check(source: Path, runtime: Path) -> list[str]`; entrypoints의 위 runtime_api 인수, `RUNTIME_API = 1`, `RuntimeCompatibilityError(RuntimeError)`.

- [x] 테스트 먼저 작성한다. 임시 source에 `model_effort_router/__init__.py`, `entrypoints.py`를 만들고 설치 후 파일 내용 일치를 검증한다. 이전 설치의 `removed.py`는 갱신 후 없어야 한다. `__pycache__`, `.pyc`는 복사하지 않는다.
- [x] `shutil.copytree` 및 최종 staging rename에 각각 오류를 주입해서 기존 runtime의 파일 내용이 보존되고 설치 실패가 보고되는 테스트를 작성한다. source/target이 같거나 target이 source 내부인 경우 변경 전에 거절한다.
- [x] CLI/gate API 불일치는 공통 `RuntimeCompatibilityError(RuntimeError)`, hook API 불일치는 무출력 0이 되는 테스트를 기존 entrypoint 테스트에 추가한다. 일치한 API는 기존 반환값·호스트 지정 동작을 유지한다.

```python
# tests/test_entrypoints.py에 추가할 핵심 검증
with self.assertRaises(entrypoints.RuntimeCompatibilityError):
    entrypoints.cli("codex", runtime_api=999)
self.assertEqual(entrypoints.hook("claude", Path("/tmp/plugin"), runtime_api=999), 0)
```

- [x] `python3 -m unittest tests.test_core_install tests.test_entrypoints`로 RED를 확인한다.
- [x] 기존 sync 스크립트의 파일 목록/내용 검사 방식을 설치기에 재사용하고 설치 인터페이스를 구현한다. 기존 진입점의 실제 호출 앞에서 API를 확인한다. hook 검사는 기존 실패 보호 안에 둔다.
- [x] 같은 명령으로 GREEN을 확인한다. 실행 시 Task 1·2를 함께 반영하므로 삭제할 사본을 다시 생성하는 중간 sync는 생략한다.
- [x] 코드·보안 리뷰 후 Task 1·2·3·4·문서 변경을 하나의 `refactor: import one shared core across plugins` 구현 커밋에 포함한다. 중간 사본 재생성과 실행 불가능한 과도 상태를 피한다.

## Task 2: 플러그인 연결 전환과 120개 사본 삭제

**Files:** Modify 3개 `plugins/*/bin/mer`, 3개 `bin/mer-gate`, 2개 `hooks/user_prompt_submit.py`; Delete `plugins/*/model_effort_router/`, `scripts/sync_plugin.py`; Modify `tests/test_plugin_bundle.py`, `tests/test_claude_plugin.py`, `tests/test_antigravity_plugin.py`, `tests/hook_helpers.py`, `tests/test_mer_cli.py`, `evaluation/probes/claude_live_probe.sh`, `AGENTS.md`, `README.md`, 3개 plugin README 및 관련 skill 설치 안내.

**Interfaces:** Task 1의 runtime 위치와 진입점. `plugin_root`는 기존 위치로 전달한다. 호스트 manifest의 실행 경로는 유지한다.

- [x] 먼저 테스트를 새 계약으로 바꾼다. 3개 플러그인에 `model_effort_router/`가 없음을 검증한다. 코어를 임시 공용 runtime에 한 번 설치하고 플러그인 세 개를 각기 다른 임시 폴더로 복사한다.
- [x] 소스 checkout, PYTHONPATH에 기대지 않고 `sys.executable -I`로 각 CLI/gate/hook을 실행한다. 모든 호스트가 동일한 코어를 쓰는 증거는 공용 entrypoints stub이 자신의 `__file__`와 host/root 인수를 출력하게 하여 경로가 같음을 검증한다.

```python
# tests/test_plugin_bundle.py의 구조 회귀 검증
for plugin in plugins:
    self.assertFalse((plugin / "model_effort_router").exists())
# 별도 임시 runtime에 설치한 core로 세 플러그인을 실행한다.
# entrypoints stub이 반환한 Path(__file__).resolve()는 모두 동일해야 한다.
```

- [x] runtime 없음, 상대 override, 손상된 package, API 불일치, 공백이 있는 설치 경로를 검사한다. CLI/gate는 2와 안내, hook은 무출력 0을 검증한다. 악의적인 cwd의 동명 package가 선택되지 않도록 검증한다.
- [x] 평가 도구의 checkout `PYTHONPATH` 및 `python -m model_effort_router.cli` 실행은 유지한다. `evaluation/probes/claude_live_probe.sh`의 plugin CLI 호출은 공유 runtime 설치/override 전제를 문서화하며 실제 live probe는 실행하지 않는다.
- [x] 기존 동작 검증: CLI 기본 host와 `--host` override, Antigravity chat/run 제한, gate JSON, hook 재귀 방지·추천 문구·실제 plugin_root의 리뷰 실행 명령을 유지한다. 테스트 fake registry가 필요한 일반 subprocess는 명시적으로 테스트 경로를 전달하고, 격리 smoke에는 fake registry를 쓰지 않는다.
- [x] RED 확인 후 loader를 아래 부트스트랩으로 바꾼다. 중복되는 최소 경로 계산은 loader의 불가피한 연결 코드이며 기능 로직을 넣지 않는다. runtime 검증/실패 안내 처리도 실제 필요한 짧은 코드만 쓴다.

```python
import os
import sys
from pathlib import Path
home = Path.home()
xdg = Path(os.environ.get("XDG_DATA_HOME", str(home / ".local/share")))
base = xdg if xdg.is_absolute() else home / ".local/share"
runtime = Path(os.environ.get("MER_CORE_PATH", str(base / "model-effort-router/runtime")))
# relative runtime은 import 전에 거절한다. hook에서는 같은 실패를 조용히 종료한다.
if not runtime.is_absolute() or not (runtime / "model_effort_router/entrypoints.py").is_file():
    print("Shared core missing: see README installation instructions", file=sys.stderr)
    sys.exit(2)
sys.path.insert(0, str(runtime))
from model_effort_router.entrypoints import cli
sys.exit(cli("codex", runtime_api=1))
```

- [x] fallback으로 기존 번들 코어를 사용하지 않는다. API 검사·import 오류는 CLI/gate에서 필요한 오류만 잡고 일반 제품 실행 오류를 숨기지 않는다. hook에는 기존 BaseException 실패 보호를 유지한다.
- [x] 120개 사본과 sync 스크립트를 삭제한다. 모든 sync import·번들 동일성 테스트·사본 존재 검증을 제거/대체한다. BUNDLES 목록 대신 테스트에서 plugin root 목록을 사용한다.
- [x] AGENTS.md의 sync 규칙을 단일 소스/공용 runtime 설치 검사 규칙으로 교체한다. README와 skill에 공유 코어를 먼저 설치하고 코어 업데이트 후 재설치하는 절차를 명시한다. 이전 계획은 역사 기록으로 두되 상단에 이 계획으로 대체되었음을 표시한다.
- [x] `python3 -m unittest tests.test_core_install tests.test_entrypoints tests.test_plugin_bundle tests.test_claude_plugin tests.test_antigravity_plugin tests.test_mer_cli tests.test_gate_cli tests.test_user_prompt_submit`를 실행한다.
- [x] 테스트가 GREEN이고 독립 리뷰를 통과하면 통합 구현 커밋에 포함한다.

## Task 3: JSONL 파서 중복 제거

**Files:** Create `model_effort_router/events.py`, `tests/test_events.py`; Modify `model_effort_router/host/codex_exec.py`, `model_effort_router/difficulty/subscription.py`, `evaluation/usage.py`, `evaluation/live_runner.py`; 관련 기존 테스트 보존.

**Interfaces:** `iter_events(text: str)`는 dict 이벤트를 순서대로 yield한다. 파일 읽기·메시지 선택·usage 정책은 호출부 책임이다.

- [x] 잘못된 JSON, 빈 줄, 배열/null/숫자, 정상 dict 순서의 회귀 테스트를 먼저 작성한다.

```python
self.assertEqual(list(iter_events('bad\n[]\nnull\n42\n{"type":"a"}\n{"type":"b"}')),
                 [{"type": "a"}, {"type": "b"}])
```

- [x] `python3 -m unittest tests.test_events`로 RED 확인 후 아래 공통 반복자를 구현한다.

```python
import json

def iter_events(text):
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            yield event
```

- [x] 두 `_events` 구현과 subscription의 파싱 루프를 공통 함수 import로 교체한다. live_runner.read_events는 기존 missing-file `[]`, 파일 읽기 오류 동작을 보존한다. subscription의 마지막 메시지/usage 선택 및 메시지 부재 예외, evaluation의 누적 usage 계산도 유지한다.
- [x] 파서·subscription·Codex 실행·평가 사용량·live runner 관련 기존 테스트와 신규 테스트를 실행한다. `python3 -m unittest tests.test_events tests.test_subscription tests.test_eval_usage tests.test_eval_live_runner tests.test_mer_cli`를 실행한다.
- [x] 독립 리뷰 후 통합 구현 커밋에 포함한다.

## Task 4: 호스트 공통 동작과 테스트 중복 정리

**Files:** Create `model_effort_router/adapters/common.py`; Modify 3개 adapter, `model_effort_router/host/__init__.py`, 3개 host executor, `tests/hook_helpers.py`, `tests/test_claude_plugin.py`, `tests/test_user_prompt_submit.py` 및 adapter 테스트.

**Interfaces:** `adapters.common.ResolvedProfile(tier, model, requested_effort, applied_effort)`의 applied_effort는 Optional[str]; `apply_support(requested, supported)`는 현재 Codex 알고리즘. `host.session_env(base)`는 새 dict를 반환한다.

- [x] 3개 adapter의 현 model/effort 결과, Claude effort 없음, Antigravity model slug·불변 매핑, Codex 빈 supported 거절을 회귀 테스트로 고정한다. session_env 입력 dict가 변하지 않음을 검사한다.
- [x] 동일한 프로필 자료형과 현재 이미 재사용 중인 effort 지원 계산 및 EFFORT_ORDER를 `adapters/common.py`로 옮긴다. Codex의 `_apply_support`가 필요한 기존 호출은 import alias로 호환시킨다. host별 노력 순위가 같은지 전체 지원 값으로 확인하고 현재 순위 의미를 보존한다. 설정 validation은 호스트별 차이를 보존하기 위해 현재 위치에 유지한다. 짧은 반복 검증을 위한 범용 validator는 만들지 않는다.
- [x] 두 session_env 구현을 현재 비어 있는 `host/__init__.py`의 아래 한 함수로 모으고 3개 executor에서 `from . import session_env`로 import한다. executor를 import하는 hosts.py에는 함수를 두지 않아 순환 import를 피한다. 새 범용 host 기반 클래스는 만들지 않는다.

```python
def session_env(base):
    return {**base, "MER_CLASSIFIER": "1"}
```

- [x] hook 테스트 준비를 기존 `tests/hook_helpers.py`에 모은다. host/plugin/payload 기본값만 인수로 전달하고 host별 추천 문구 검증은 유지한다. 같은 manifest/sync 검증은 공통 plugin 테스트에 한 번만 둔다.
- [x] evaluation의 7줄 결과 쓰기 반복, manifest/skill의 유사 구조, 최소 loader bootstrap은 유지한다. 일반화 비용이 큰 호스트 명령·usage 처리·프로세스 종료도 유지한다. 이들은 기능 차이/작은 접착 코드이며 제거 대상과 구분해서 최종 보고한다.
- [x] `python3 -m unittest tests.test_codex_adapter tests.test_claude_adapter tests.test_antigravity_plugin tests.test_claude_exec tests.test_antigravity_exec tests.test_user_prompt_submit tests.test_claude_plugin tests.test_plugin_bundle` 통과 후 독립 리뷰하고 통합 구현 커밋에 포함한다.

## Task 5: 단일 소스 검증과 PR 정정

**Files:** Modify README 구조·개발 설명과 Codex/Claude version manifest; 검증 결과를 이 계획에 기록.

- [x] 전체 `python3 -m unittest discover -s tests`, `git diff --check`를 실행한다. 설치 관련 테스트는 실제 HOME을 변경하지 않고 임시 경로에서만 실행한다. 모델 호출·플러그인 실제 설치는 필요 없다.
- [x] 변경 모듈의 coverage를 기존 사용 가능한 coverage 도구 또는 stdlib trace로 측정한다. 적용 가능한 변경 줄 커버리지 80% 이상을 확인하고 전체 저장소/분기 커버리지와 혼동하지 않는다.
- [x] `git ls-files 'plugins/*/model_effort_router/*'` 결과가 비어 있고 원본 외 코어 구현 사본이 없는지 확인한다. 3개 격리 플러그인이 동일 runtime의 `__file__`를 반환하는 테스트가 필수다.
- [x] 전체 파일 내용 해시·함수 AST·연속 코드 블록 비교를 다시 실행한다. JSONL와 session_env 중복 제거, 남은 bootstrap/host별 차이를 설명한다. 원본 사본 삭제로 추가 8,337줄이 사라진 것과 새 공통 코드 줄 수를 별도 보고한다.
- [x] code-reviewer, python-reviewer, 설치 경로 처리에 대한 security-reviewer 리뷰에서 CRITICAL/HIGH를 해결한다. 순환 import, 실패 후 기존 runtime 보존, cwd에서 코어를 잘못 읽는 문제를 확인한다.
- [x] 두 version manifest를 최종 동작 변경에 맞춰 `0.5.0`으로 올린다. version 필드가 없는 Antigravity에는 임의로 추가하지 않는다. 호환 API 1과 배포 버전은 별개다.
- [x] 검증·문서 변경을 통합 구현 커밋에 포함한다. 기존 사용자 PR 생성 지시에 따라 push하고 기존 PR #2의 제목·한글 설명을 최종 공유 코어 구조 중심으로 다시 작성한다.

## 완료 조건

- [x] 소스 구현은 루트 `model_effort_router/` 1벌뿐이며 plugin 안에는 0벌이다.
- [x] 사용자 runtime 설치는 호스트와 무관하게 1개다. 플러그인 세 개가 이를 import함을 경로로 입증한다.
- [x] 임시 runtime 설치 후 원본 checkout을 사용할 수 없는 조건에서도 플러그인 CLI/gate/hook이 동작한다.
- [x] 미설치·오류·호환성 실패 동작과 기존 호스트별 사용자 동작이 검증된다.
- [x] 원본의 JSONL 파서/session_env/공통 adapter 데이터 및 테스트 준비 중복을 제거했다.
- [x] sync 규칙·검사·문서의 이전 사본 계약이 실제 구조와 맞게 교체되었다.
- [x] 전체 테스트·독립 리뷰·중복 재검사가 통과하고 남은 작은 반복을 명시했다.


## 구현·검증 결과 — 2026-10-06

- 계획 커밋: `8b06231`; 구현은 기존 main 기반 `codex/shared-plugin-entrypoints`에서 계속했다. 작업별 중간 커밋·임시 번들 재생성 대신 최종 동작을 `30cb3d8` 구현 커밋으로 묶었다. 최종 보안 재검사에서 발견한 필수 파일 symlink 거절은 별도 fix 커밋으로 추가했다.
- `plugins/*/model_effort_router/`의 120개 파일·8,337줄을 삭제했다. `cli.py`, `entrypoints.py`, `flow.py`, `review.py`를 비롯한 코어는 저장소 루트에만 있다. 세 플러그인 폴더·manifest 실행 경로는 유지한다.
- 신규 공통 코드: `events.py` 13줄, `adapters/common.py` 20줄, 기존 빈 `host/__init__.py`에 6줄. JSONL 파싱, 불변 프로필 결과·effort fallback, 세션 환경 guard를 재사용하고 hook 테스트 준비도 합쳤다.
- RED: installer/API 테스트의 미구현 import·속성 실패, plugin 새 계약의 34개 실패, 공통 parser 미구현 실패, adapter·session identity 실패를 확인했다. GREEN: 전체 `python3 -m unittest discover -s tests` 696개 통과. `ruff check model_effort_router scripts tests evaluation`, `git diff --check` 통과.
- stdlib trace 실행 줄 커버리지(줄 0 메타데이터 제외): installer 72/74=97.3%, entrypoints 25/25=100%, events 9/9=100%, adapters/common 13/13=100%, host/__init__ 3/3=100%. 이는 위 모듈 대상 값이며 전체 저장소·분기 커버리지 수치가 아니다.
- code-reviewer·python-reviewer·security-reviewer 독립 리뷰 완료. 불필요한 Path import를 제거했고, package symlink를 installer와 8개 loader에서 거절하고 loader는 필수 진입점 파일 symlink도 거절하며 회귀 테스트로 고정했다. 외부 의존성이 없는 제품 코드의 빈 requirements로 `pip_audit --disable-pip --no-deps` 실행: 알려진 취약점 없음.
- 파일 SHA-256, 5줄 이상 함수 AST, 8줄 연속 블록을 제품·평가·설치 파일에서 재검사했다. 비어 있지 않은 동일 파일·동일 함수 AST는 없으며 연속 블록은 8개 loader의 bootstrap에만 남는다. 공유 코어를 import하기 전에 필요한 경로 계산·실패 처리는 이 짧은 연결 코드로 유지한다. 호스트별 validation·명령·usage 차이와 evaluation의 작은 결과 쓰기 반복도 일반화하지 않았다.
- 설치 계약은 `python3 scripts/install_core.py`로 사용자당 runtime 한 개를 미리 준비하는 방식이다. 별도 checkout이 필요하며 marketplace plugin 설치만으로는 준비되지 않는다. 개발용 `MER_CORE_PATH`는 절대 checkout 경로를 허용한다. plugin 변경만으로 runtime이 갱신되지 않으며 API 변경 시 세 plugin과 runtime을 함께 갱신한다.
- 명시한 core 경로가 없을 때 cwd/PYTHONPATH/site-packages의 동명 core로 fallback하지 않는다. 이를 일반 Python 실행에서도 검증했다. Python 자체의 site 초기화·sitecustomize 격리는 이 로더 계약의 범위가 아니다.
- 설치 실패 시 기존 코어 보존·복구를 검증했고 복구 자체가 실패하면 backup을 남긴다. 동시 설치·실행 중 완전 무중단 갱신은 구현하지 않았다. 사용자 HOME 설치·실제 모델 호출은 수행하지 않았다.

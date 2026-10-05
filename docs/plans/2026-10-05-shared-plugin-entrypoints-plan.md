# Shared Plugin Entrypoints Implementation Plan

> **For agentic workers:** 구현 시 `superpowers:executing-plans` 또는 `superpowers:subagent-driven-development`를 적용하고 아래 체크박스를 순서대로 완료한다. 이 문서는 계획이며, 현재 제품 코드 변경은 없다.

**Goal:** 세 플러그인의 공통 실행 준비·호출 로직을 원본 `model_effort_router/`로 모으고 플러그인은 최소 로더로 유지한다.

**Architecture:** 원본에 `entrypoints.py`를 추가하고 각 플러그인이 자기 번들 안의 모듈을 import한다. 기존 `cli.py`, `gate/run.py`, `host/codex_hooks.py`의 로직은 재사용한다. 코어 사본과 `scripts/sync_plugin.py`는 유지한다.

**Tech Stack:** Python 3 표준 라이브러리, unittest/mock, 기존 플러그인 번들 동기화 스크립트.

**Spec:** 이 대화에서 정한 구조와 아래 보존 조건. 사본 제거·배포 방식 변경이 아니라 플러그인 내부 실행 코드의 공통화다.

## 작업 기준

- 브랜치: `codex/shared-plugin-entrypoints`, 로컬 `main`의 `a0ac6b50b69c6bfeb970c535119c36156ba37aca`에서 생성했다.
- 플러그인 manifest, 설치 경로, hook command, 실행 파일 이름과 실행 권한을 유지한다.
- `--host`가 플러그인 기본 호스트보다 우선하고, 플러그인 기본값은 셸의 `MER_HOST`보다 우선한다.
- Codex·Claude의 gate는 기존처럼 호스트를 지정한다. Antigravity gate는 기존처럼 `MER_HOST`를 변경하지 않는다.
- CLI/gate의 stdout, stderr, 종료 코드와 오류 전파를 보존한다. hook은 실패 시 출력 없이 0으로 종료한다.
- hook의 `MER_CLASSIFIER=1` 재귀 방지와 실제 플러그인 경로를 사용하는 리뷰 명령을 보존한다.
- Antigravity에 hook이나 자동 `run` 지원을 추가하지 않는다.
- 새 의존성, 호스트 자동 추론, 범용 dispatcher·registry, 코어 파일 이름 변경은 범위 밖이다.
- 제품 코드는 원본에서만 수정하고 세 번들 사본은 `sync_plugin.py`로 생성한다.

## 변경 파일과 책임

| 파일 | 변경 |
|---|---|
| `model_effort_router/entrypoints.py` | 공통 CLI/gate/hook 진입점 추가 |
| `plugins/{codex,claude,antigravity}-model-effort-router/bin/mer` | 경로 설정 후 공통 CLI 호출 |
| `plugins/{codex,claude,antigravity}-model-effort-router/bin/mer-gate` | 경로 설정 후 공통 gate 호출 |
| `plugins/{codex,claude}-model-effort-router/hooks/user_prompt_submit.py` | 경로 설정·import 실패 보호 후 공통 hook 호출 |
| `tests/test_entrypoints.py` | 공통 진입점 동작 검증 |
| `tests/test_claude_plugin.py` | 소스 문자열 검사 제거, 실제 호스트 선택·hook 회귀 검증 유지 및 확장 |
| `tests/test_plugin_bundle.py` | 설치된 번들만으로 실행되는지 검증 |
| `plugins/*/model_effort_router/` | 원본 동기화 결과 |
| `README.md` | 공통 진입점과 사본 관리 방식 설명 |
| 두 호스트의 버전 포함 manifest | 구현 완료 시 `0.4.0` → `0.4.1` |

Antigravity manifest에는 version 필드가 없으므로 임의로 추가하지 않는다.

## 1. 공통 진입점 추가: RED → GREEN

**Interfaces:** `cli(host: str) -> int`, `gate(host: str | None = None) -> int`, `hook(host: str, plugin_root: Path) -> int`.

- [ ] `tests/test_entrypoints.py`에 테스트를 먼저 작성한다. CLI/gate 종료 코드 전달, 대상 호출 시 호스트 값, gate의 생략된 호스트, hook event와 경로 전달 및 실패 처리를 검증한다.

```python
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from model_effort_router import entrypoints

class EntrypointsTest(unittest.TestCase):
    def test_cli_pins_host_and_returns_exit_code(self):
        with patch.dict(os.environ, {"MER_HOST": "codex"}):
            with patch("model_effort_router.cli.main",
                       side_effect=lambda: 7 if os.environ["MER_HOST"] == "claude" else 9):
                self.assertEqual(entrypoints.cli("claude"), 7)

    def test_gate_without_host_preserves_environment(self):
        with patch.dict(os.environ, {"MER_HOST": "claude"}):
            with patch("model_effort_router.gate.run.main", return_value=3) as main:
                self.assertEqual(entrypoints.gate(), 3)
                self.assertEqual(os.environ["MER_HOST"], "claude")
                main.assert_called_once_with()

    def test_hook_passes_event_and_plugin_root(self):
        root = Path("/tmp/plugin")
        with patch.dict(os.environ, {}):
            with patch("model_effort_router.host.codex_hooks.main", return_value=0) as main:
                self.assertEqual(entrypoints.hook("codex", root), 0)
                main.assert_called_once_with("UserPromptSubmit", root)

    def test_hook_failure_is_silent_success(self):
        with patch.dict(os.environ, {}):
            with patch("model_effort_router.host.codex_hooks.main", side_effect=SystemExit(2)):
                self.assertEqual(entrypoints.hook("claude", Path("/tmp/plugin")), 0)
```

- [ ] 위 예제에 gate의 명시적 호스트 지정, CLI/gate 예외 전파, hook의 일반 예외 검증을 추가한다. 테스트는 `patch.dict`로 프로세스 환경을 복원한다.
- [ ] `python3 -m unittest tests.test_entrypoints`를 실행해 새 모듈이 없어서 실패하는지 확인한다.
- [ ] 다음 최소 구현을 추가한다. 대상 모듈은 함수 안에서 import한다.

```python
"""Shared process entrypoints for self-contained plugin bundles."""
import os

def cli(host):
    os.environ["MER_HOST"] = host
    from .cli import main
    return main()

def gate(host=None):
    if host is not None:
        os.environ["MER_HOST"] = host
    from .gate.run import main
    return main()

def hook(host, plugin_root):
    try:
        os.environ["MER_HOST"] = host
        from .host.codex_hooks import main
        return main("UserPromptSubmit", plugin_root)
    except BaseException:
        return 0
```

프로세스 환경 지정은 기존 로더의 동작을 그대로 옮기는 경계 작업이다. `SubscriptionBackend`가 자식 환경을 `os.environ`에서 만들기 때문에 CLI에 환경 사본만 전달하면 기존과 달라진다. 일반 비즈니스 데이터의 불변성 원칙은 유지한다. hook의 `BaseException` 보호는 기존 실패 동작을 보존하기 위한 것이며 CLI/gate에는 적용하지 않는다.

- [ ] 같은 테스트가 통과하는지 확인한다.

## 2. 플러그인 로더 연결 변경 및 번들 동기화

**Consumes:** 위 세 공통 함수. **Produces:** 기존 경로에서 그대로 실행되는 플러그인 진입점.

- [ ] `tests/test_claude_plugin.py`의 `os.environ` 대입 문자열 검사를 제거한다. 실행 권한 검사와 기존 subprocess 호스트 선택 테스트는 유지한다. 이는 삭제되는 구현 표현을 검사하던 테스트이며 사용자 동작 검증은 계속 남는다.
- [ ] Codex와 Claude의 missing-core 테스트를 각각 실행한다. 임시 디렉터리에 hook 파일만 복사하고 `python3 -I <copied-hook>`를 실행한다. 격리 옵션과 임시 cwd로 원본 코어가 우연히 import되는 것을 막는다. 결과는 종료 코드 0, stdout/stderr 모두 빈 문자열이어야 한다.
- [ ] 설치 번들 테스트는 원본 저장소에 의존하지 않도록 각 플러그인 전체를 임시 디렉터리로 복사한다. `sys.executable -I`로 CLI dry-run과 gate를 실행한다. 두 CLI 호스트의 기본 선택·명시 override, Antigravity chat dry-run 및 지원하지 않는 run의 종료 코드 2를 확인한다.
- [ ] 기존 로더에서 새 함수 호출을 기대하는 연결 테스트가 실패하는 것을 확인한다.
- [ ] 세 CLI 로더를 다음 형식으로 바꾼다. `HOST` 대신 각각 `codex`, `claude`, `antigravity`를 문자열로 명시한다.

```python
#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from model_effort_router.entrypoints import cli
sys.exit(cli("codex"))
```

- [ ] gate 로더도 `entrypoints.gate`를 import하고 Codex는 `gate("codex")`, Claude는 `gate("claude")`, Antigravity는 `gate()`를 호출한다.
- [ ] 두 hook 로더를 다음 형식으로 바꾼다. Claude에는 `claude`를 전달한다. 코어가 import되지 않을 때의 보호는 로더에 남겨야 한다.

```python
#!/usr/bin/env python3
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    from model_effort_router.entrypoints import hook
    code = hook("codex", ROOT)
except BaseException:
    code = 0
sys.exit(code)
```

- [ ] `python3 scripts/sync_plugin.py`를 실행한 다음 `python3 scripts/sync_plugin.py --check`가 `in sync`인지 확인한다.
- [ ] 아래 관련 테스트를 실행한다. API 변경에 맞추기 위해 사용자 동작의 기대값을 바꾸지 않는다.

```bash
python3 -m unittest tests.test_entrypoints tests.test_plugin_bundle tests.test_claude_plugin tests.test_antigravity_plugin tests.test_gate_cli tests.test_user_prompt_submit
```

## 3. 문서·버전·최종 검증

- [ ] `README.md`의 저장소 구조에 `entrypoints.py` 역할을 설명하고, 기존의 “두 플러그인” 표현을 세 번들에 맞춘다. 별도 문서를 추가하지 않는다.
- [ ] Codex `.codex-plugin/plugin.json`과 Claude `.claude-plugin/plugin.json`의 version을 `0.4.1`로 올린다. marketplace와 hook command는 변경하지 않는다.
- [ ] `python3 -m unittest discover -s tests`와 `python3 scripts/sync_plugin.py --check`를 실행한다.
- [ ] 변경 모듈의 coverage 80% 이상을 측정한다. 현재 `python3`에는 `coverage`가 없으므로 실행 전에 기존 개발 환경의 도구 가용성을 확인한다. 도구가 없다면 측정 불가를 명시하고 80%를 충족했다고 주장하지 않는다. 테스트 도구가 준비되면 아래 명령을 사용하며 제품 의존성에는 추가하지 않는다.

```bash
python3 -m coverage run --source=model_effort_router.entrypoints -m unittest tests.test_entrypoints
python3 -m coverage report --fail-under=80
```

- [ ] code-reviewer와 python-reviewer에게 변경 diff의 동작 보존, import 실패 처리, 호스트 우선순위와 테스트 누락을 리뷰받고 CRITICAL/HIGH 지적을 해결한다.
- [ ] `git diff --check`와 `git diff`로 원본·세 번들 일치, 실행 권한, 범위 밖 변경 여부를 확인한다. 실제 모델 호출, 설치, push, PR 생성은 이 계획의 검증에 필요하지 않다.

## 완료 조건과 현재 확인 결과

- 공통 실행 동작은 원본 `entrypoints.py`가 소유하고 로더에는 경로 설정·호스트 이름·hook import 실패 보호만 남는다.
- 세 번들만 별도로 복사해도 정상 실행되며 원본 경로·전역 패키지 설치가 필요하지 않다.
- 호스트 선택, gate 결과, hook 출력·오류·재귀 방지와 Antigravity 지원 제한이 이전과 같다.
- 브랜치 생성 전 작업 트리는 깨끗했고 현재 HEAD는 기준 main과 같다.
- 계획 작성 기준으로 번들은 `in sync`; 기존 관련 테스트 69개가 통과했다. 신규 진입점·전체 테스트·coverage는 구현 후 검증한다.

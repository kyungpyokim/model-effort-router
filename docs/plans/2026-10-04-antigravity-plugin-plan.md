# Antigravity Plugin Implementation Plan

> **Execution status (2026-10-04):** Minimum CLI bundle implemented on `codex/antigravity-plugin`. Task 0 confirmed the headless JSON contract and model availability. Hook and automated `mer run` remain deferred because reliable turn extraction and enforced read-only isolation are unverified.

**Goal:** 기존 Model-Effort Router의 검증된 범위를 Antigravity 네이티브 플러그인으로 제공한다. 현재 번들은 `mer chat` 및 수동 프로필을 지원한다.

**Architecture:** 난이도 분류·정책·Test Gate는 기존 코어를 재사용한다. Antigravity 모델 매핑, 실행 어댑터, 훅 입출력만 추가한다. 네이티브 플러그인을 사용하므로 별도 VS Code 확장이나 MCP 서버는 만들지 않는다.

**Tech Stack:** Python 표준 라이브러리, 기존 unittest, Antigravity CLI `agy`, JSON manifest/hooks, Markdown skill.

**Spec:** 사용자 요청 “antigravity용 플러그인 추가 계획 세워”; 기존 제품 정책은 [원 기획서](model-effort-router-pluggable-difficulty-plan.md)를 따른다. Antigravity 고유 범위·계약·출시 조건은 이 문서에 정리한다.

## 범위와 제약

- 대상은 이 저장소의 세 번째 호스트 번들 `plugins/antigravity-model-effort-router/`로 가정한다.
- 기존 Codex/Claude 설치 방식, 기본 호스트, 모델 매핑은 유지한다.
- `economy/balanced/frontier`, `medium/high/xhigh`, L1–L5 정책을 그대로 사용한다.
- 새 의존성, SDK 기반 오케스트레이터, 모델별 정적 subagent 템플릿은 추가하지 않는다.
- 사용자의 전역 설정·인증·권한은 자동 변경하지 않는다. 구현 중 임시 디렉터리에서 무해한 `agy -p` 모델 추론을 검증했다. 전역 설치나 설정 변경은 수행하지 않았다.
- 향후 훅은 추천 전용으로 fail-open이어야 한다. 현재는 검증 조건이 충족되지 않아 hooks.json을 배포하지 않는다.
- `--dangerously-skip-permissions`를 제품 명령에 넣지 않는다. `--sandbox`가 읽기 전용을 보장한다고 가정하지 않는다.
- 새 로직은 실패하는 unittest를 먼저 작성하고 구현한다. 오프라인 회귀 테스트와 새 adapter/parser branch coverage 80% 이상을 확인한다.
- 실측은 `agy` 1.2.16의 help/models, 로컬 plugin validate, 임시 디렉터리의 무해한 JSON 추론이다. 설치·resume·강제 격리는 미검증이다.

## 확인한 사실과 설계 영향

| 근거 | 확인한 내용 | 계획에 미치는 영향 |
|---|---|---|
| 로컬 CLI, 2026-10-04 | `agy 1.2.16`; JSON 출력, `--model`, `--effort`, `--prompt-interactive`, `--mode plan` 지원 | 임시 디렉터리에서 무해한 JSON 추론을 확인했다. plan 모드의 권한 격리는 입증되지 않아 run은 비활성화했다. |
| 로컬 `agy models` | Flash 3.8 low/medium/high, Sonnet 5.5 low/medium/high, Opus 5.5 low/medium/high slug 노출 | 후보 매핑은 Flash/Sonnet/Opus. 이름과 옵션이 실제 선택에 반영되는지 Phase 0에서 확인한다. |
| [Plugins 공식 문서](https://antigravity.google/docs/plugins/) | 루트 `plugin.json`, `skills/`, 루트 `hooks.json`; 로컬 설치 지원 | `.codex-plugin`이나 `.claude-plugin` manifest를 복사하지 않는다. |
| [Hooks 공식 문서](https://antigravity.google/docs/hooks/) | `PreInvocation`은 모델 호출마다 실행되고 직접적인 `prompt` 필드가 없다. `transcriptPath`가 입력되고 `injectSteps`로 컨텍스트를 넣는다. | `UserPromptSubmit`을 이름만 바꿔 이식할 수 없다. transcript 스키마와 사용자 턴 중복 제거가 선행 조건이다. |
| [Headless 공식 문서](https://antigravity.google/docs/cli/headless/) | JSON 결과·conversation resume·usage 제공; 권한 거절이 있어도 exit 0일 수 있다. | 프로세스 종료 코드만으로 성공 판정하지 않는다. 실제 gate를 실행하고 결과를 검증한다. |
| `scripts/sync_plugin.py` | 호스트별 코어 복사 및 drift 검사 | 세 번째 Antigravity bundle을 등록한다. |
| `cli.py`, `subscription.py` | Claude 외 호스트가 Codex로 처리되는 분기 존재 | host 등록만 하면 오실행된다. chat/no-route/classifier 경로도 함께 수정해야 한다. |

공식 문서상 가능, 로컬 help에서 가능, 실제 동작 검증 완료를 구분해서 README에 표시한다.

## 선택한 구현 순서

1. **호스트 계약 검증:** 모델/effort와 임시 디렉터리 headless JSON 응답을 확인한다. resume, 강제 격리, 훅 transcript는 미검증으로 남겼다.
2. **최소 번들 (완료):** 네이티브 manifest + skill + `mer chat` + `mer-gate`를 제공한다.
3. **자동 추천 훅 (보류):** 관측 transcript가 decorated/truncated여서 사용자 turn 경계가 증명될 때까지 추가하지 않는다.
4. **전체 실행 흐름 (보류):** CLI permission isolation과 resume 검증 후 `mer run`을 활성화한다.

대안인 skill만 배포하는 방식은 빠르지만 현재 제품의 실행·분류 기능을 충분히 제공하지 못한다. VS Code 확장은 네이티브 플러그인으로 해결되는 기능을 중복 구현하므로 제외한다. Phase 0에서 일부 계약이 실패하면 해당 기능만 비활성화하고 최소 번들을 출시한다.

## 파일별 책임

| 파일 | 변경 내용 |
|---|---|
| `docs/spikes/antigravity-host-api.md` | Phase 0 버전, 명령, 검증 결과, 개인정보를 제거한 입출력 증거 기록 |
| `model_effort_router/adapters/antigravity.py` | frozen 설정·ResolvedProfile, tier→모델 및 effort→지원값 매핑 |
| `model_effort_router/host/antigravity_exec.py` | CLI argv, strict JSON parsing, usage envelope validation, explicitly rejected automated execution |
| `model_effort_router/host/hosts.py` | `ANTIGRAVITY`와 host 등록 |
| `model_effort_router/cli.py` | Antigravity chat/no-route/cwd 및 미지원 run의 명시적 오류 |
| `model_effort_router/difficulty/subscription.py` | Antigravity 구독 분류 분기 및 알 수 없는 host 거절 |
| `model_effort_router/host/antigravity_hooks.py` | 조건부 추가: PreInvocation 입력 검증·사용자 턴 식별·중복 방지·추천 JSON |
| `scripts/sync_plugin.py` | 세 번째 코어 번들 동기화 |
| `plugins/antigravity-model-effort-router/` | manifest, README, skill, bin/mer, bin/mer-gate, 동기화한 코어; 훅 검증 후 hooks.json과 hooks/pre_invocation.py |
| `tests/test_antigravity_adapter.py`, `tests/test_antigravity_exec.py` | 매핑·argv·결과·usage·오류 계약 |
| `tests/test_antigravity_plugin.py`, `tests/test_antigravity_hooks.py` | 번들·wrapper·실제 형식 fixture 훅 테스트 |
| 기존 `tests/test_mer_cli.py`, `tests/test_subscription.py`, `tests/test_claude_plugin.py` | host 분기, classifier, 번들 목록 회귀 테스트 확장 |

`flow.py`는 같은 host 계약으로 재사용한다. 검증 결과상 계약이 맞지 않으면 우선 `mer run`을 비활성화하며 새 실행 엔진을 만들지 않는다. 코어 수정 후 번들 사본은 항상 sync 스크립트로 생성한다.

## Task 0: 실제 호스트 계약 확정

**Files:** Create `docs/spikes/antigravity-host-api.md`; 테스트용 임시 저장소는 저장소 밖에 만든다.

- [ ] 로컬에서 다음 읽기 전용 명령을 재확인하고 버전·모델 목록을 기록한다.

```bash
agy --version
agy --help
agy models
agy help plugin
```

- [x] 사용자의 “진행” 지시에 따라 임시 디렉터리에서 무해한 `agy -p` JSON probe를 실행하고 CLI가 해당 model/effort 인자를 받아 JSON SUCCESS를 반환하는 것을 확인했다. 결과 envelope는 실제 resolve된 model slug를 되돌려주지 않아 서비스 측 모델 식별은 미검증이며, conversation resume도 미검증이다.
- [x] economy Flash 3.8, balanced Sonnet 5.5, frontier Opus 5.5 slug를 확인했다. medium/high는 실제 제공 effort를 쓰고 xhigh는 high로 적용하며 추상 요청값은 결과에 보존한다.
- [x] `--mode plan`이 `/plan` 지침을 주입하는 것을 transcript에서 확인했다. 툴/파일 격리를 확인하지 않았으므로 읽기 전용 보장으로 취급하지 않는다. `mer run`과 plan/review chat은 명시적으로 차단한다.
- [x] SUCCESS 결과와 usage shape, 누락 usage를 parser fixture로 검증한다. ERROR fixture도 테스트에 있다. resumed usage 의미는 미검증이므로 raw usage만 보존하고 run에서 소비하지 않는다.
- [x] `agy plugin validate`로 로컬 bundle을 검사했다. 사용자 전역 플러그인 설치는 하지 않았다. hook trust/timing은 미검증이며 훅은 포함하지 않는다.
- [x] own probe transcript는 decorated `USER_INPUT`이고 `truncated_fields`에 content가 있었다. 안정적인 사용자 turn ID/offset을 입증하지 못해 hook을 보류한다.
- [x] 결정: chat 활성화, hook/run 비활성화. 근거는 [host API spike](../spikes/antigravity-host-api.md) 참조.

## Task 1: 모델 매핑과 최소 실행 어댑터

**Files:** Create `adapters/antigravity.py`, `host/antigravity_exec.py`와 해당 테스트; Modify `host/hosts.py`, `difficulty/subscription.py`, `tests/test_subscription.py`.

**Interfaces:** `resolve(profile, config) → ResolvedProfile(tier, model, requested_effort, applied_effort)`; 기존 Host 필드와 동일. exec는 기존 `session_env`와 strict `parse_stream`만 구현한다. full-run parser entrypoint는 fail-closed 처리하며 `UsageTracker`는 run 활성화 시 추가한다.

- [x] 실패 테스트를 먼저 추가했다: 세 tier의 검증된 slug, xhigh→high, 잘못된 매핑·effort 거절, 입력 config 불변.
- [x] 기존 Codex frozen dataclass/helper를 재사용하고 검증된 모델/effort만 담았다. xhigh 요청은 실제 effort와 별도 기록한다.
- [x] JSON parser 테스트를 먼저 추가했다: 성공→thread_id/text, 오류 status·잘못된 JSON·누락 ID/response→예외, 누락 usage→None, bool/음수 token→예외. thinking/cache token의 포함 관계를 확인해 이중 합산하지 않는다.

첫 RED 테스트의 구체적인 계약은 다음과 같다. `AntigravityResultError(ValueError)`와 `parse_stream(text)`를 `host/antigravity_exec.py`에 구현한다. fixture의 success shape는 Phase 0 실측과 대조한 뒤 사용한다.

```python
import json
import unittest

from model_effort_router.host.antigravity_exec import (
    AntigravityResultError, parse_stream,
)


class AntigravityExecTest(unittest.TestCase):
    def test_result_contract(self):
        success = {"conversation_id": "fixture-id", "status": "SUCCESS",
                   "response": "done"}
        result = parse_stream(json.dumps(success))
        self.assertEqual((result.thread_id, result.text, result.usage),
                         ("fixture-id", "done", None))
        with self.assertRaises(AntigravityResultError):
            parse_stream(json.dumps({**success, "status": "ERROR"}))
```

Run: `python3 -m unittest tests.test_antigravity_exec -v`; 처음에는 import 오류로 실패하고 최소 parser 구현 후 통과해야 한다.

- [x] interactive child에서 기존 `session_env` guard를 재사용한다. 자동 실행/timeout runner는 미지원이다.
- [x] subscription에 명시적인 Antigravity 거절 분기를 추가했다. 기존 `build_prompt`, `decision_from_text`, 임시 cwd를 재사용한다. tools/hooks/MCP 격리가 검증되지 않으면 구독 분류는 실행 전에 지원 오류를 내며 Codex를 대신 실행하지 않는다. 그 경우 기존 nimble/jev 또는 manual 설정을 문서화한다.
- [x] 외부 classifier 없이 시작하는 manual 예시를 README에 제공했다: 설정 `{"router": {"mode": "manual"}}`와 요청 첫 줄 `/router session=balanced:medium`. backend 선택을 플러그인 설치기가 사용자 설정에 자동 기록하지 않는다.
- [ ] 동일 프로필로 접히는 ladder 단계는 실제 동작을 문서화한다. 이 작업에서 전체 라우팅 정책을 재설계하지 않는다.
- [x] adapter/parser와 subscription 관련 테스트를 실행했다.

```bash
python3 -m unittest tests.test_antigravity_adapter tests.test_antigravity_exec tests.test_subscription -v
```

## Task 2: 네이티브 번들과 mer chat

**Files:** Create `plugins/antigravity-model-effort-router/{plugin.json,README.md,skills/model-effort-router/SKILL.md,bin/mer,bin/mer-gate}` 및 `tests/test_antigravity_plugin.py`; Modify `cli.py`, `scripts/sync_plugin.py`, `tests/test_mer_cli.py`, `tests/test_claude_plugin.py`.

- [x] 테스트부터 추가했다: wrapper 기본 host 고정, `--host` 명시값 우선, dry-run에서 모델 호출 0회, chat/no-route 모두 agy 사용, 공백 cwd 지원, Codex/Claude 결과 유지.
- [x] `_chat_argv`, no-route 기본 명령, `_exec` cwd 처리에 Antigravity 분기를 추가하고 argv/cwd를 fake CLI로 검증했다. `agy`는 `--cd`가 없으므로 Claude처럼 작업 디렉터리를 변경한다. child argv는 리스트로 전달하고 요청을 shell 문자열로 실행하지 않는다.
- [x] interactive 시작은 검증된 `--prompt-interactive`·model·effort를 사용한다. plan/review 요청은 읽기 전용이 검증되지 않으면 시작 전에 오류로 끝낸다. 미지원 `mer run`은 classifier/host 호출 전에 exit 2로 끝낸다.
- [x] 공식 schema에 맞는 최소 manifest를 추가했다.

```json
{
  "name": "model-effort-router",
  "description": "Route development requests to Antigravity models and effort."
}
```

- [x] `BUNDLES`에 `PLUGINS / "antigravity-model-effort-router" / "model_effort_router"`를 추가한다. 기존 2개 bundle exact-list assertion을 3개로 갱신하고 각 bundle drift 검사는 유지한다.
- [x] skill/README에 chat/gate와 제약을 설명했다. run과 자동 추천은 각 검증 단계 완료 후 설명을 추가한다. CLI와 IDE 설치 방법은 구분한다. 기존 Codex/Claude marketplace 파일에는 Antigravity entry를 추가하지 않는다.
- [x] `agy plugin validate plugins/antigravity-model-effort-router` 통과. 실제 설치 성공은 이 검사만으로 주장하지 않는다.
- [x] **최소 번들 완료 조건:** subscription 격리 검증 통과 또는 README에 필수 Jev/Nimble/manual 설정을 안내하고 해당 fixture에서 비드라이런 chat이 주입한 `exec_fn`에 정확한 agy argv를 전달하는 테스트 통과. subscription이 미지원인 기본 설정에서는 어떤 호스트 subprocess도 시작하지 않고 설정 방법을 포함한 오류를 반환하는 테스트도 통과해야 한다.

```bash
python3 scripts/sync_plugin.py
python3 scripts/sync_plugin.py --check
python3 -m unittest tests.test_antigravity_plugin tests.test_mer_cli tests.test_plugin_bundle tests.test_claude_plugin -v
```

## Task 3: 자동 추천 훅 — 보류

**Files:** Create `host/antigravity_hooks.py`, bundle `hooks.json`, `hooks/pre_invocation.py`, `tests/test_antigravity_hooks.py`.

- [ ] 실제 transcript 형식 fixture로 테스트부터 작성한다: 첫 요청 1회, 같은 요청의 tool loop 0회, 같은 문구의 새 사용자 턴 1회, skill/hook/subagent 출력 0회, `MER_CLASSIFIER=1` 0회.
- [ ] PreInvocation payload에는 prompt가 없으므로 검증된 최신 사용자 턴만 추출한다. 전체 transcript를 분류기에 보내지 않는다. stdin은 64 KiB, transcript 읽기는 최대 마지막 1 MiB로 제한한다. transcriptPath는 정규 파일인지 확인하고, symlink나 검증된 Antigravity 로그 디렉터리 밖 경로는 거절한다. 사용자 턴 시작을 읽기 범위에서 찾지 못하거나 schema가 바뀌면 `{}`로 종료한다.
- [ ] 멱등 키는 `(conversationId, 안정적인 사용자 turn ID 또는 offset)`을 사용한다. 내용 hash만 쓰면 동일한 새 요청이 사라지므로 사용하지 않는다. 기존 state 디렉터리에 작은 원자적 상태 파일을 저장하고 동일 키 동시 호출도 중복 분류하지 않도록 stdlib 배타적 생성으로 claim한다.
- [ ] conversation ID는 비어 있지 않은 최대 256자 문자열로 검증한다. 로그 파일명에는 기존 `route_log.log_path()`의 정규화·해시 처리를 재사용하고, 멱등 상태 키는 ID와 turn ID를 JSON 직렬화한 값의 SHA-256으로 만든다. workspacePaths가 복수이면 transcript에 해당 턴의 workspace가 명시된 경우에만 repo 설정을 선택하며, 불명확하면 추천을 생략한다.
- [ ] `route()`와 `session_plan()`을 재사용한다. 기존 `advice.render()`는 mer run 추천과 Claude/Codex model alias 가정이 있으므로 초기 버전은 짧은 Antigravity 전용 출력만 만든다. 공용 renderer를 위한 추상 계층은 추가하지 않는다.
- [ ] `injectSteps: [{ephemeralMessage: ...}]`로 난이도·위험·추천 모델/effort·plan-first를 전달한다. 즉시 모델 전환이나 권한 allow/deny를 수행하지 않는다.
- [ ] modelName에 정확한 effort가 없으면 이미 추천값과 일치한다고 추정하지 않는다. `/effort` 명령 존재도 가정하지 않고 검증된 UI/CLI 변경 방법만 안내한다.
- [ ] invalid JSON, transcript 없음, classifier timeout, import 실패는 `{}`/exit 0. 오류 로그에는 고정 코드와 예외 타입만 남기고 prompt·transcript·토큰은 남기지 않는다.
- [ ] CLI/IDE에서 각각 설치 후 새 요청→추천 1회→tool loop 중 반복 없음→다음 요청 재추천을 확인한다. 지원되지 않는 surface는 README에 명시한다.

```bash
python3 -m unittest tests.test_antigravity_hooks tests.test_antigravity_plugin -v
```

**실패 시:** hooks.json을 배포하지 않고 skill + mer chat을 유지한다. `invocationNum == 0`으로 첫 요청만 처리하는 코드를 전체 사용자 턴 지원으로 포장하지 않는다.

## Task 4: mer run, gate, escalation, 독립 review — 보류

**Files:** Modify `host/antigravity_exec.py`, `cli.py`, bundle skill/README; extend `tests/test_antigravity_exec.py`, `tests/test_mer_cli.py`, `tests/test_mer_flow.py`.

**Interfaces:** `session_argv(profile, prompt, sandbox, config, subagents=None)`, `resume_argv(profile, thread_id, prompt, config, subagents=None)`, `UsageTracker.delta(thread_id, usage)`를 기존 `flow.py`와 맞춘다.

- [ ] fake runner를 이용해 L2 implement→gate passed, L4 plan-first→implement→gate→review, gate failed→같은 conversation 재개, max escalation 종료 테스트를 먼저 작성한다.
- [ ] `agy -p --output-format json --model … --effort …`와 `--conversation`를 검증된 옵션으로 구성한다. 읽기 전용 작업은 Task 0에서 검증한 제한을 적용한다. 설정/훅/MCP를 통한 쓰기 우회도 막지 못하면 해당 기능은 활성화하지 않는다.
- [ ] 검증된 usage 범위에 따라 tracker를 선택한다. 호출별이면 Claude tracker와 같은 복사, 누적이면 Codex tracker와 같은 delta를 사용한다. resumed process에서도 누적인지 별도로 확인한다.
- [ ] subagent 0 차단이 보장되지 않으면 read-only plan/review를 시작하지 않는다. 양수 concurrency cap이 미지원이면 prompt hint 한계로 문서화하고 강제 제한으로 주장하지 않는다.
- [ ] exit 0·SUCCESS라도 gate failed/incomplete는 완료로 보고하지 않는다. permission soft-denial로 작업이 누락된 fixture도 검증한다.
- [ ] 전체 구현이 검증된 뒤 run 비활성 guard를 제거하고 skill/자동 추천에 run·독립 review 안내를 추가한다.

```bash
python3 -m unittest discover -s tests -v
python3 scripts/sync_plugin.py --check
```

## 완료·출시 기준

- [x] 오프라인 unit/integration 회귀 통과(641 tests); 별도 coverage 도구는 설치되지 않아 adapter/parser branch coverage 100%. 개발용 임시 venv에만 coverage를 설치해 adapter/parser branch coverage를 측정했다. 제품 dependency에는 추가하지 않았다.

```bash
python3 -m venv /tmp/mer-antigravity-test-venv
/tmp/mer-antigravity-test-venv/bin/python -m pip install coverage
/tmp/mer-antigravity-test-venv/bin/python -m coverage run --branch --source=model_effort_router -m unittest discover -s tests
/tmp/mer-antigravity-test-venv/bin/python -m coverage report --include='*/antigravity*.py' --fail-under=80
```

- [ ] 별도 승인된 fixture E2E: 설치/skill 로딩, chat 모델 적용, 훅 중복 없음, run gate/escalation/review는 활성화된 범위에서 통과.
- [x] 전체 suite와 3개 bundle drift 검사 통과.
- [ ] code-reviewer와 Python/security 리뷰로 CRITICAL/HIGH 지적 해소. 코드 변경 시 수행하고 계획 작성 단계에서는 제품 테스트 통과를 주장하지 않는다.
- [x] README에 사용 기능, backend 제약, CLI validate/install 명령과 read-only limitation을 기록했다. IDE 동작은 미검증.

예상 작업량은 Phase 0 반나절–1일, 최소 번들 1일, 훅 1일, 전체 run 검증 1–2일이다. 이는 범위 기반 추정이며, transcript 안정성·읽기 전용 보장 여부가 일정과 출시 범위를 결정한다.

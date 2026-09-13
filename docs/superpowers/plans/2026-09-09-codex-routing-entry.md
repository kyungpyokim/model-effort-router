# Codex 새 세션 라우팅 진입 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 새 Codex 세션에서 구현·설계·리뷰·리팩터링·디버깅 작업을 시작할 때 모델 라우팅 절차를 빠뜨리지 않도록, 안전한 정책 주입 훅과 명확한 실행 계약을 추가한다.

**Architecture:** Codex 플러그인의 `SessionStart`와 `UserPromptSubmit` 훅은 2초 이내에 고정된 `additionalContext`만 반환한다. 실제 분류와 위임은 훅이 끝난 뒤 기존 `model-effort:route`, route JSON, 에이전트 프로필을 그대로 사용하며 한 작업당 한 번만 수행한다. 훅은 준수 가능성을 높이는 알림 장치이고, 확실한 새 세션 라우팅이 필요할 때는 기존 `codex-route` 런처가 진입점을 소유한다.

**Tech Stack:** Codex native hooks, Python 3 표준 라이브러리, JSON, `unittest`, 기존 Codex plugin/launcher.

**Spec:** `docs/superpowers/plans/2026-09-09-codex-routing-entry.md`의 `Global Constraints`와 `Acceptance`가 2026-09-09 사용자 요구를 self-contained 계약으로 고정한다.

## Global Constraints

- 훅에서 classifier, `codex`, worker, 네트워크 호출을 실행하지 않는다.
- 훅에서 원래 프롬프트를 차단하지 않으며 `decision: block`을 반환하지 않는다.
- 동기 훅은 고정 문구만 출력하고 `timeout: 2`를 사용한다. 비동기 훅은 context 도착 경쟁 때문에 사용하지 않는다.
- `hooks/hooks.json` 자동 탐색을 사용하고 manifest에 `hooks` 경로를 중복 선언하지 않는다.
- `SessionStart` source는 `startup`, `resume`, `clear`, `compact`를 포함한다. `UserPromptSubmit`에는 무시되는 matcher를 두지 않는다.
- 모든 새 코딩 작업 유형을 대상으로 삼되, 잡담·상태 확인에는 추가 분류를 강제하지 않는다.
- 같은 작업의 후속 요청은 저장된 전체 route JSON을 재사용한다. 유형이 바뀌거나 범위·위험이 실질적으로 커지면 재분류한다. 별개의 리뷰 요청은 `review`로 새로 분류한다. compact/resume 후 기존 JSON을 찾을 수 없으면 재사용을 가장하지 않고 새로 분류한다.
- 작업 전환을 regex로 추측하거나 전역 session boolean으로 후속 요청을 가리지 않는다.
- classifier는 분류 전용 prompt와 output schema를 받으며 아직 route JSON이 없다. classifier는 자기 분류 역할만 수행한다. 선택된 executor는 전체 route JSON과 no-reroute 지침을 받아 재분류하지 않는다. 공유 `session_id`만으로 예외를 판단하지 않는다. 두 예외는 모델이 따르는 역할 계약이며 기술적 강제나 인증 경계로 표현하지 않는다.
- 첫 버전에는 `PreToolUse` 전역 차단이나 strict tool gate를 넣지 않는다.
- route JSON schema v3, 모델 매핑, `--route-file` replay, `execution_strategy: direct`는 재사용하고 재구현하지 않는다.
- Codex 전용 훅을 Claude Code·Antigravity 플러그인이나 `scripts/sync_bundle.py` 공유 목록에 복사하지 않는다.
- `verification.recommended`는 실행 권고 메타데이터다. 계획상 권고인 `contract_review`, `broad_regression`을 실행 완료로 표시하지 않는다.
- 설치·활성화는 훅 신뢰를 뜻하지 않는다. 현재 훅 정의를 native trust 흐름에서 승인하고 `trusted_hash`를 직접 생성하거나 위조하지 않는다.
- 기존 stale `trusted_hash`는 이번 기능과 무관하므로 정리하지 않는다.
- `/Users/kimkyungpyo/.codex/AGENTS.md`는 실행 승인 후 백업하고 Model Recommendations 부분만 좁게 수정한다. 나머지 ECC 지침은 보존한다.
- 작업 시작 시 `git fetch origin`, `origin/main`의 `dfffa37fd1c8324bed2dd17511d2cc817bddf851` 이상을 확인하고 새 `codex/codex-routing-entry` 브랜치를 만든다.

---

## File Map

| 파일 | 책임 |
|---|---|
| `plugins/codex-model-effort-router/hooks/hooks.json` | SessionStart/UserPromptSubmit에 짧은 정책 주입 훅 등록 |
| `plugins/codex-model-effort-router/scripts/routing_policy_hook.py` | stdin payload를 소비하고 event별 `additionalContext` JSON만 출력 |
| `tests/test_codex_policy_hook.py` | 출력 계약, 시간 제한, 외부 프로세스 미실행, hooks 설정 검증 |
| `scripts/validate_bundle.py` | Codex 패키지에 훅 파일과 유효한 설정이 포함됐는지 정적 검증 |
| `plugins/codex-model-effort-router/skills/route/SKILL.md` | 새 작업/후속 작업/리뷰/실행자 no-reroute 계약 명시 |
| `plugins/codex-model-effort-router/.codex-plugin/plugin.json` | Codex 전용 동작 변경의 semver 갱신; hooks 경로는 선언하지 않음 |
| `plugins/codex-model-effort-router/README.md`, `README.md` | 알림 훅의 보장 범위, launcher 보장 경로, trust/검증 절차 문서화 |
| `/Users/kimkyungpyo/.codex/AGENTS.md` | 설치 후 전역 opt-in 정책을 라우터 우선으로 통일; repo PR에는 포함하지 않음 |

### Task 1: 안전한 훅 계약을 RED 테스트로 고정

**Files:**
- Create: `tests/test_codex_policy_hook.py`
- Planned create: `plugins/codex-model-effort-router/hooks/hooks.json`
- Planned create: `plugins/codex-model-effort-router/scripts/routing_policy_hook.py`

**Interfaces:**
- Consumes: Codex hook stdin JSON과 argv event 이름 `SessionStart` 또는 `UserPromptSubmit`.
- Produces: `hookSpecificOutput.hookEventName`과 1,000자 이하 `additionalContext`; exit code `0`.

- [ ] **Step 1: 훅 설정 RED 테스트를 작성한다.** JSON을 읽어 SessionStart source 네 종류, matcher 없는 UserPromptSubmit, command의 `${PLUGIN_ROOT}`, `timeout == 2`, `additionalContextLimit == 1000`을 assert한다.
- [ ] **Step 2: 금지 동작을 설정 수준에서 고정한다.** command에 `router.py`, `codex-route`, `codex exec`, `claude`, `agy`가 없고 `async`가 활성화되지 않았음을 assert한다.
- [ ] **Step 3: 프로세스 미실행 RED 테스트를 작성한다.** 임시 `PATH`에 호출 시 counter를 남기는 가짜 `codex`, `claude`, `agy`를 두고 훅을 실행한다. subprocess timeout은 스케줄링 여유를 포함해 3초로 잡고 counter가 생성되지 않아야 한다. 1초 미만은 실제 host에서 측정할 지연 목표이며 혼잡한 CI의 단일 벽시계 assertion으로 고정하지 않는다.
- [ ] **Step 4: context 계약 RED 테스트를 작성한다.** 두 event를 각각 실행해 새 코딩 작업은 route-first, 같은 작업은 full route JSON 재사용, 별도 리뷰는 새 `review` route, 잡담은 미분류, classifier/executor는 no-reroute라는 문구를 assert한다.
- [ ] **Step 5: RED를 확인한다.** Run: `python3 -m unittest discover -s tests -p test_codex_policy_hook.py -v`. Expected: 훅 파일이 아직 없어 FAIL.

### Task 2: 정책만 주입하는 최소 Codex 훅 구현

**Files:**
- Create: `plugins/codex-model-effort-router/hooks/hooks.json`
- Create: `plugins/codex-model-effort-router/scripts/routing_policy_hook.py`
- Test: `tests/test_codex_policy_hook.py`

**Interfaces:**
- Consumes: event 이름과 JSON payload. prompt 내용, session id, 저장소 내용은 분기 입력으로 사용하지 않는다.
- Produces: event 이름을 보존한 작은 `additionalContext`; malformed stdin에서도 정상 종료하고 외부 작업을 하지 않는다.

- [ ] **Step 1: stdlib 훅 스크립트를 구현한다.** `json.load(sys.stdin)`로 payload를 소비하고 상수 정책 문구를 JSON으로 출력한다. 파일 I/O, `subprocess`, 네트워크, sleep, temp state는 추가하지 않는다.
- [ ] **Step 2: 정책 문구를 고정한다.** 구현·설계·리뷰·리팩터링·디버깅의 새 작업은 본격 작업 전에 route하고, 동일 작업 후속은 기존 전체 JSON을 재사용하며, distinct review는 새 review route로 처리하도록 쓴다.
- [ ] **Step 3: 역할 예외를 같은 문구에 포함한다.** 분류 전용 prompt/schema를 받은 classifier는 분류만 수행하고, 전체 route JSON과 선택 모델/effort를 받은 executor는 지정된 작업만 수행한다. 둘 다 route를 재귀 호출하지 않는다. 실제 CLI/app 검증에서 재귀가 관찰되면 설치 확대를 중단하고 child 범위 역할 신호가 필요한지 먼저 진단한다.
- [ ] **Step 4: hooks 설정을 추가한다.** standard `hooks/hooks.json` 자동 탐색만 사용해 SessionStart와 UserPromptSubmit을 스크립트에 연결한다. `.codex-plugin/plugin.json`에는 hooks 경로를 넣지 않는다.
- [ ] **Step 5: GREEN을 확인한다.** Run: `python3 -m unittest discover -s tests -p test_codex_policy_hook.py -v`. Expected: 모든 테스트 PASS, 호출 timeout 없음, 가짜 실행기 counter 없음.
- [ ] **Step 6: 과거 실패 형태가 돌아오지 않았는지 diff로 확인한다.** Run: `rg -n "subprocess|decision.*block|timeout.*600|codex-route|router.py" plugins/codex-model-effort-router/hooks plugins/codex-model-effort-router/scripts/routing_policy_hook.py`. Expected: 금지 호출/차단/600초 timeout 없음.
- [ ] **Step 7: Task 1-2를 커밋한다.** Commit: `feat(codex): inject route-first session policy`.

### Task 3: 라우팅 skill, 패키지 검증, 문서 정합성

**Files:**
- Modify: `plugins/codex-model-effort-router/skills/route/SKILL.md`
- Modify: `scripts/validate_bundle.py`
- Modify: `plugins/codex-model-effort-router/.codex-plugin/plugin.json`
- Modify: `plugins/codex-model-effort-router/README.md`
- Modify: `README.md`
- Test: `tests/test_codex_policy_hook.py`

**Interfaces:**
- Consumes: 기존 schema v3 route JSON과 agent profile 선택 결과.
- Produces: 한 번 분류된 전체 JSON, 선택 model/effort, no-reroute 지침을 executor에 함께 전달하는 문서 계약.

- [ ] **Step 1: skill 계약 테스트를 먼저 추가한다.** 새 작업 유형, same-task reuse, distinct review, executor no-reroute, 잡담 제외 문구가 존재하는지 assert한다.
- [ ] **Step 2: skill 설명과 절차를 좁게 수정한다.** `Use before implementation` 범위를 모든 substantive coding task로 넓히고 기존 classify-once/route-file replay 절차는 보존한다.
- [ ] **Step 3: bundle validator를 강화한다.** Codex hook JSON/스크립트 존재, event 등록, 2초 timeout, manifest의 hooks 중복 선언 부재를 검사한다. Claude/Antigravity 훅 존재는 요구하지 않는다.
- [ ] **Step 4: Codex manifest version을 `2.1.2`로 올린다.** Codex 전용 기능 변경이므로 Claude Code와 Antigravity의 `2.1.1` metadata는 바꾸지 않는다. validator의 플랫폼별 기대 version도 이에 맞춘다.
- [ ] **Step 5: README를 갱신한다.** 훅은 route-first 준수를 돕지만 hard enforcement는 아니며, 확실한 CLI 진입은 `plugins/codex-model-effort-router/bin/codex-route -- "<task>"`가 소유한다고 명시한다.
- [ ] **Step 6: 집중 검증을 실행한다.** Run: `python3 -m unittest discover -s tests -p test_codex_policy_hook.py -v && python3 scripts/validate_bundle.py`.
- [ ] **Step 7: 전체 회귀를 실행한다.** Run: `python3 -m unittest discover -s tests -v && git diff --check`. 기존 101개를 포함한 전체 suite가 PASS해야 하며 실제 개수는 실행 결과로 보고한다.
- [ ] **Step 8: Codex 전용 범위를 확인한다.** Run: `git diff --name-only` 후 Claude/Antigravity plugin과 `scripts/sync_bundle.py`에 변경이 없음을 확인한다.
- [ ] **Step 9: Task 3를 커밋한다.** Commit: `docs(codex): define automatic routing entry contract`.

### Task 4: 승인된 소스를 전역 opt-in과 설치 캐시에 적용

**Files:**
- Modify after backup: `/Users/kimkyungpyo/.codex/AGENTS.md`
- Generated by installer: versioned Codex plugin cache outside repo

**Interfaces:**
- Consumes: 검증된 Codex plugin `2.1.2` 소스.
- Produces: 전역 라우터 우선 지침, 설치/활성 plugin, 사용자가 신뢰한 현재 hook definition.

- [ ] **Step 1: 전역 AGENTS를 timestamp backup한다.** 실제 경로를 출력해 확인한 뒤 같은 디렉터리에 `.bak-YYYYMMDD-HHMMSS`를 만든다.
- [ ] **Step 2: Model Recommendations 구역만 패치한다.** 정적 모델 추천표를 이 문서의 전역 지침 문구로 교체한다. 실패 시에도 라우터가 반환한 fallback JSON과 실패 원인을 보고하고 별도 표로 모델을 다시 고르지 않는다. 나머지 ECC, 외부 액션, 보안 지침은 byte-level diff로 보존 여부를 확인한다. 훅 미신뢰 상태에서는 초기 smoke만 수행하고 자동 라우팅 활성화 완료로 보고하지 않는다.
- [ ] **Step 3: 설치 명령을 dry-run한다.** Run: `python3 scripts/install_plugins.py codex --scope user --dry-run`. 대상이 현재 저장소의 Codex plugin인지 확인한다.
- [ ] **Step 4: 소스 검증 후 Codex plugin만 재설치한다.** 현재 설치를 제거해야 할 경우 정확한 ID `model-effort@model-effort-router-bundle`만 대상으로 삼고 즉시 같은 저장소의 `2.1.2`를 설치한다.
- [ ] **Step 5: native hook trust를 완료한다.** Codex가 보여주는 현재 `hooks/hooks.json` 정의를 확인해 승인한다. config에 `trusted_hash`를 직접 쓰지 않는다.
- [ ] **Step 6: 설치 상태와 cache 내용을 대조한다.** `codex plugin list`의 enabled/version, cache의 manifest version, hooks JSON/script SHA-256을 source와 비교한다. installed/enabled만으로 성공 처리하지 않는다.
- [ ] **Step 7: rollback 절차를 기록한다.** 문제가 생기면 `2.1.2`를 제거하고 AGENTS backup을 복원한 뒤 이전 `2.1.1`을 재설치할 수 있도록 실제 backup/cache 경로를 남긴다.

### Task 5: 실제 새 세션에서 세 단계 증거를 분리 검증

**Files:** None. 사용자가 시작한 새 Codex CLI/app 세션의 transcript만 수집한다.

**Interfaces:**
- Consumes: 신뢰된 훅, 활성 plugin, 새 사용자 프롬프트.
- Produces: `hook fired`, `route generated`, `selected executor ran`을 각각 입증하는 timestamped 기록.

- [ ] **Step 1: CLI startup 세션을 새로 연다.** plain `codex` 진입에서 구현 요청을 제출하고 SessionStart/UserPromptSubmit 훅 시각을 기록한다. `codex-route` smoke와 섞지 않는다.
- [ ] **Step 2: route 생성을 별도로 확인한다.** full schema v3 JSON의 `task_type`, `effective_level`, `steps[].model`, `steps[].effort`, `source`를 확인한다. 훅 반환 뒤 substantive 작업 전에 라우팅 결정이 한 번 생성되어야 한다. 한 결정 안의 primary→fallback cascade는 정상이며 native classifier 프로세스 2회를 중복 라우팅으로 오판하지 않는다.
- [ ] **Step 3: executor 실행을 별도로 확인한다.** 실제 위임 명령/agent profile의 model과 effort가 route JSON과 정확히 같고, executor가 classifier를 재호출하지 않았는지 확인한다.
- [ ] **Step 4: 새 유형을 표본 검증한다.** 새 세션으로 design, review, refactor 요청을 각각 실행해 세 증거를 확인한다. 결과 level 자체를 고정하지 않고 JSON과 executor 일치만 판정한다.
- [ ] **Step 5: follow-up 경계를 확인한다.** 같은 범위의 후속 요청은 기존 full JSON을 재사용해 classifier count가 늘지 않고, 새로운 리뷰 작업은 `task_type: review`의 새 route를 만든다. 범위·위험 증가와 기존 JSON 분실도 재분류 사례로 검증한다.
- [ ] **Step 6: 비작업 프롬프트를 확인한다.** 잡담/간단 상태 질문에서는 훅이 context를 주입해도 classifier/worker를 강제로 실행하지 않는지 확인한다.
- [ ] **Step 7: resume/clear/compact를 확인한다.** 각 source에서 훅은 빠르게 반환하고 UI가 멈추지 않으며, semantic follow-up 규칙이 유지되는지 확인한다.
- [ ] **Step 8: Codex desktop app을 별도로 검증한다.** 사용자가 명시적으로 새 app task를 시작한 뒤 동일 세 증거를 수집한다. CLI 성공을 app 성공으로 대체하지 않는다.
- [ ] **Step 9: launcher 보장 경로를 smoke한다.** `codex-route -- "<task>"`가 한 번 분류한 route의 model/effort로 새 세션을 여는지 확인하되, 이는 native app hook의 성공 증거와 분리해 보고한다.

### Task 6: 최종 자체 리뷰와 PR 준비

**Files:** Task 1-3의 repo 변경만 포함한다. 전역 AGENTS/cache는 PR diff에 포함하지 않는다.

- [ ] **Step 1: acceptance mapping을 점검한다.** 새 작업 5종, follow-up reuse, fresh review, no chat classifier, no recursion, no blocking, CLI/app 분리 검증이 각각 테스트나 transcript에 연결됐는지 확인한다.
- [ ] **Step 2: placeholder와 금지 패턴을 검색한다.** 계획 placeholder는 육안으로 확인하고, Run: `rg -n "decision.*block|timeout.*600|subprocess" plugins/codex-model-effort-router/hooks plugins/codex-model-effort-router/scripts/routing_policy_hook.py tests/test_codex_policy_hook.py`로 런타임 금지 패턴을 확인한다.
- [ ] **Step 3: 전체 검증을 한 번만 최종 실행한다.** Run: `python3 -m unittest discover -s tests -v && python3 scripts/validate_bundle.py && git diff --check`.
- [ ] **Step 4: 독립 리뷰를 받는다.** hook lifecycle, classify-once/reuse, child exemption, Codex-only packaging, trust/install 문서만 범위로 지정한다.
- [ ] **Step 5: 리뷰 지적을 수정하면 관련 집중 테스트와 전체 suite를 다시 실행한다.** 미실행 권고를 PASS로 표시하지 않는다.
- [ ] **Step 6: PR에는 소스 commit, 정확한 테스트 수, validator 결과, 실제 CLI/app 증거, 미검증 host 경계를 적는다.** hard enforcement라고 표현하지 않는다.

## Acceptance

- [ ] 모든 hook 호출은 1초 미만에 끝나고 classifier/worker/network를 실행하거나 원 프롬프트를 차단하지 않는다.
- [ ] 새 substantive coding task는 route-first 문맥을 받고, 같은 작업 후속은 route JSON을 재사용하며, 새 review는 review route를 만든다.
- [ ] 선택 executor는 full route JSON의 model/effort와 일치하고 재분류하지 않는다.
- [ ] 잡담/상태 요청에는 불필요한 classifier가 실행되지 않는다.
- [ ] source와 설치 cache의 hook digest가 일치하고 현재 정의가 native trust를 받는다.
- [ ] CLI와 desktop app에서 `hook → route → executor` 증거가 각각 확인된다. 확인되지 않은 host는 미검증으로 보고한다.
- [ ] 기존 `codex-route`는 강한 CLI 진입점으로 계속 동작하고 schema v3 replay 회귀가 없다.
- [ ] Claude Code·Antigravity 산출물은 변경되지 않고 전체 테스트, bundle validation, diff check가 통과한다.

## 구현에 사용할 출력·정책 예시

`plugins/codex-model-effort-router/hooks/hooks.json`의 최소 설정:

```json
{
  "hooks": {
    "SessionStart": [{
      "matcher": "^(startup|resume|clear|compact)$",
      "hooks": [{"type": "command", "command": "python3 \"${PLUGIN_ROOT}/scripts/routing_policy_hook.py\" SessionStart", "timeout": 2, "additionalContextLimit": 1000}]
    }],
    "UserPromptSubmit": [{
      "hooks": [{"type": "command", "command": "python3 \"${PLUGIN_ROOT}/scripts/routing_policy_hook.py\" UserPromptSubmit", "timeout": 2, "additionalContextLimit": 1000}]
    }]
  }
}
```

훅 정책 상수의 실제 문구(전체 출력 context는 1,000자 이하 유지):

```text
For a new implementation, design, review, refactoring, or debugging task, invoke model-effort:route before substantive repository work. Save the complete route JSON and delegate with its exact model and effort; replay saved steps without classifying again. Reuse the existing route for same-scope follow-ups. Re-route for a distinct task, a new review, materially increased scope/risk, or a missing prior route. Do not route casual chat or status-only questions. If you are already the classification-only process, perform that classification only. If you are an executor given a complete route, execute only your assigned work; return escalation evidence to the parent instead of recursively routing. Report classifier fallback as fallback, not successful semantic routing. Briefly show task_type, effective_level, selected model/effort and source before delegation. Follow higher-priority instructions and explicit user constraints.
```

스크립트 인터페이스와 malformed 입력 처리 예시:

```python
def hook_response(event: str, payload: object) -> dict:
    if event not in {"SessionStart", "UserPromptSubmit"} or not isinstance(payload, dict):
        return {}
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": POLICY}}

# POLICY는 위 고정 문구 그대로 정의한다. main은 event argv 하나와 stdin JSON만 읽는다.
# JSONDecodeError/UnicodeDecodeError 또는 잘못된 argv는 stderr에 짧은 진단을 남기고
# {}와 exit 0을 반환한다. prompt·credential·transcript는 로그에 출력하지 않는다.
```

출력 계약의 실행 테스트 예시 (`HOOK`은 저장소 기준 신규 스크립트 경로):

```python
def test_hook_returns_context_without_blocking(self):
    proc = subprocess.run(
        [sys.executable, str(HOOK), "UserPromptSubmit"],
        input=json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "전체 리뷰해"}),
        text=True, capture_output=True, timeout=3, check=True,
    )
    output = json.loads(proc.stdout)
    self.assertNotIn("decision", output)
    self.assertNotEqual(output.get("continue"), False)
    specific = output["hookSpecificOutput"]
    self.assertEqual(specific["hookEventName"], "UserPromptSubmit")
    self.assertLessEqual(len(specific["additionalContext"]), 1000)
```

전역 `Model Recommendations` 구역의 교체 문구:

```text
새 구현·설계·리뷰·리팩터링·디버깅 작업은 본격 작업 전에 model-effort:route로 분류한다.
모델과 effort는 전체 route JSON의 선택 결과를 사용한다. 독립적인 추천표로 다시 선택하지 않는다.
같은 범위의 후속 작업은 기존 route를 재사용하고, 별도 리뷰·범위/위험 증가·route 분실은 재분류한다.
분류 전용 프로세스와 route를 받은 실행자는 자신의 역할만 수행하고 라우터를 재귀 호출하지 않는다.
잡담·단순 상태 질문은 제외한다. fallback과 실제 실행 실패를 정상 라우팅으로 보고하지 않는다.
```

## Known Limit

정책 주입 훅은 모델이 지침을 따를 가능성을 높이지만 current Codex app turn의 모델을 기술적으로 바꾸는 강제 경계는 아니다. hard enforcement가 실제로 필요하다는 운영 증거가 생기기 전까지는 전역 tool gate를 추가하지 않고, 확실한 실행에는 launcher-owned `codex-route`를 사용한다.

## 근거와 계획 단계의 검증 범위

- 현재 소스의 과거 커밋 `c0f0a6d:scripts/prompt_hook.py`는 훅 안에서 classifier와 worker subprocess를 동기 실행한다. 과거 세션 멈춤 기록과 대조했으며 이 구조는 재사용하지 않는다.
- [Codex 공식 hooks 문서](https://learn.chatgpt.com/docs/hooks): 자동 탐색, PLUGIN_ROOT, SessionStart source, UserPromptSubmit additionalContext, hook trust, 동기/비동기 동작 근거.
- 계획 시점 확인: `codex-cli 0.153.4`, PR #7 MERGED, `origin/main=dfffa37fd1c8324bed2dd17511d2cc817bddf851`.
- 기존 101개 통과는 앞선 수정 검증 결과다. 이번 턴은 문서만 작성했으며 훅 구현·새 테스트·실세션·설치를 수행하지 않았다.

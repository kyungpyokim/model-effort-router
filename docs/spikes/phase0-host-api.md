# Phase 0 — 호스트 API Spike 결과

- 기획서: [model-effort-router-pluggable-difficulty-plan.md](../plans/model-effort-router-pluggable-difficulty-plan.md) §3.2, §8.1, §24 Phase 0
- 대상 호스트: Codex
- 기간: 1일
- 수행자: Claude (Sonnet subagent)
- 수행일: 2026-10-01
- 환경: codex-cli 0.159.2 / macOS (Darwin 27.0.0) / ChatGPT 로그인(구독) 인증(`codex login status` = "Logged in using ChatGPT", API 키 환경 변수 0개) / 구독 플랜 등급은 확인하지 못함
- 코드·증거 위치: `spikes/phase0/` (fixture 저장소 `fixture/`, 증거 `evidence/`). `codex exec` 약 20회 실행, 대부분 `gpt-6-luna` + `low`
- 실행 경위: live 실행(구독 사용량 차감)은 사용자 사전 승인 없이 진행됐다. 이후 추가 live 실행은 사용자 명시 승인 전까지 하지 않는다.
- 검토: Opus 증거 검토(2026-10-01) 결과 `REQUEST_CHANGES`. 본 문서는 그 지적을 반영해 수정됐다(증거 없는 주장 강등, 누락 위험 추가).
- 설정 정리: 실험 중 Codex가 `~/.codex/config.toml`에 추가한 fixture `trust_level` 블록은 사용자 승인 후 삭제함.

상태 값: `미수행` / `통과` / `부분 통과` / `실패`

---

## 요약

| # | 확인 항목 | 상태 | 한 줄 결론 |
|---|---|---|---|
| 1 | 플러그인 설치 후 일반 요청에서 자동 Router 진입 | 부분 통과 | 프로젝트 로컬 `UserPromptSubmit` hook은 개발 요청·단순 질문 모두에서 자동 실행되고 컨텍스트 주입도 반영됨(hook trust 우회 플래그 사용). 플러그인 경로는 "이미 신뢰된 플러그인의 SessionStart hook이 도는 것"만 확인. 플러그인 `UserPromptSubmit`, 신규 설치·신뢰 절차는 미검증. timeout 동작은 증거 미보존. |
| 2 | 단계별 subagent에 지정한 모델·effort 실제 적용 | 부분 통과 | agent TOML(`.codex/agents/`)의 model·effort가 rollout `turn_context`와 일치(luna/medium, sol/high). 미지원 effort는 spawn 오류. 플러그인 동봉 agent는 미수행(문서상 번들 대상 아님). |
| 3 | 모델·effort 동적 지정 vs 사전 정의 조합 선택 | 통과 | 둘 다 가능: `spawn_agent`가 `model`·`reasoning_effort`를 호출 시점 인자로 받음(`fork_turns=none`에서 실험 확인. "all이면 무시"는 툴 안내문 근거, 실험 미검증). `PreToolUse` hook이 spawn 차단·기존 필드 재작성(`updatedInput`, 문서 외 동작) 가능. |
| 4 | Plan 결과·diff·Test 결과의 다음 단계 전달 | 통과(범위 제한) | Plan→Implement→테스트→Review를 1회 수동 오케스트레이션으로 실행. 결과는 1,896자까지 전문 반환 확인(실제 diff 크기는 미검증). `fork_turns=none` Review의 격리는 리뷰어 모델의 자기 보고 기준(자식 rollout 내용 미확인). |
| 5 | 구독 인증만으로 동작, timeout·취소·fallback 시 중복 실행 없음 | 부분 통과 | 구독 로그인만으로 모든 exec 성공(단 `login status` 출력은 미보존). hook timeout fail-open, 취소 시 고아 프로세스 없음은 관찰됐으나 **증거 미보존**. 취소 후 재요청 중복 실행은 미검증. |
| 6 | 구독 모델 분류 호출 가능, hook timeout 내 완료 | 부분 통과 | `codex exec` 하위 프로세스(luna/low) 호출 가능, 지연 p50 4.07s·최대 5.56s(n=5), hook 안에서 4.57s. 단 플러그인 컨텍스트가 아닌 프로젝트 로컬·bypassPermissions 환경이었고, 플러그인 hook 재귀 방지 미검증, **호출당 입력 약 29.8k 토큰으로 §8.1 전제 3(비용) 미해소**. 분류 정확도는 판단 불가(암시적 문장 5건). |

**종합 판정**: **설계 수정 후 진행**

- §2(Host Plugin 기반 제품 형태)를 뒤집을 차단 요인은 없다. 1·2번의 핵심(자동 진입 hook, subagent별 모델·effort)은 동작이 확인됐다.
- 다만 (a) 플러그인 설치 경로에서의 hook/agent 동작은 전역 설치가 필요해 미검증이고, (b) hook 신뢰(trust) 절차, `fork_turns` 제약이 기획서에 반영돼야 한다.
- **비용 위험**: 분류 호출 1회(입력 약 29.8k)가 사소한 작업 1턴 전체(t1: 29,986)와 비슷하다. L1/L2 작업에서는 분류 오버헤드가 절감분을 상쇄할 수 있다. 오케스트레이션 1회(t4) 부모 입력만 약 385k였고, 자식 사용량은 `exec --json`에 나오지 않아 §22.3 합산 측정 방법이 아직 없다.
- **재귀 위험**: 분류기의 재귀 방지는 ".codex/ 없는 cwd"뿐이다. Router hook을 플러그인·전역 hook으로 배포하면 분류용 중첩 `codex exec`에서 Router hook이 다시 실행된다. 환경 변수 가드 등 별도 방지책 필요(미검증).
- **신뢰 유지 위험**: 미신뢰 hook은 오류 없이 건너뛰며 신뢰는 `trusted_hash` 단위다. 플러그인 업데이트로 hash가 바뀌면 Router가 조용히 꺼질 가능성이 있다(미검증).
- 확인된 가장 큰 설계 이점: `spawn_agent`가 모델·effort를 동적으로 받으므로 §3.2의 `stage × profile × effort` 조합 사전 정의는 필수가 아니다(폴백으로만 유지).

---

## 1. 자동 Router 진입

**확인 방법**

- 요청 시점 hook(`UserPromptSubmit` 등)을 등록한 최소 플러그인을 설치한다.
- hook은 입력을 로그 파일에 기록하고, 라우팅 지침 한 줄을 컨텍스트에 주입한다.
- 개발 작업 요청 1건, 단순 질문 1건을 보낸다.

**확인 기준**

- 두 요청 모두 hook이 호출되는가
- 주입한 지침이 모델 응답에 반영되는가
- hook 입력에 사용자 원문 외에 어떤 필드가 오는가(세션 ID, cwd 등)
- hook timeout 기본값과 설정 가능 여부

**결과**

테스트 방식: fixture 저장소(`spikes/phase0/fixture`)의 `.codex/hooks.json`에 `UserPromptSubmit` hook을 등록하고 `codex exec`로 요청 2건을 보냈다. 프로젝트 로컬 hook은 "신뢰된 `.codex/` 계층 + hook 검토(trust)"가 있어야 로드되므로 `-c projects."<fixture>".trust_level="trusted"`와 `--dangerously-bypass-hook-trust`(호출 단위 플래그)를 사용했다. 플래그 없이 실행한 첫 호출(`t1-userprompt`)은 hook이 **실행되지 않았다**(미신뢰 hook은 조용히 건너뜀).

| 요청 | hook 호출 | 주입 지침 반영 |
|---|---|---|
| 단순 질문 (`t1a-question`) | 호출됨 | 응답이 `ROUTER_INJECTED_7Q Paris` |
| 개발 작업 (`t1b-devtask`) | 호출됨 | 응답이 `ROUTER_INJECTED_7Q done`, `hello.py` 생성 |

- hook 입력(stdin JSON) 필드: `session_id`, `turn_id`, `transcript_path`(rollout 경로), `cwd`, `hook_event_name`, `model`, `permission_mode`, `prompt`(사용자 원문 전체). 요청 종류(개발/질문)를 구분하는 필드는 없다 → 분류는 Router가 해야 한다.
- 컨텍스트 주입: stdout에 `{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"..."}}`를 출력하면 모델 응답에 반영된다(`t1a`, `t1b` 응답의 `ROUTER_INJECTED_7Q`). rollout에 developer 메시지로 기록된다는 주장은 해당 rollout(t5b)이 보존되지 않아 **철회**한다.
- timeout: **재현 증거 없음(설정·로그 덮어씀)**. 실행 중에는 timeout=2초 설정 시 6초 sleep hook이 종료되고, 생략 시 끝까지 실행되는 것으로 관찰됐다. 그러나 t5a/t5b의 hooks.json과 timeout 로그가 남지 않았고, `timing.txt`의 t5b 두 실행(6.1s, 10.5s) 중 6.1s는 설명되지 않는다. 공식 문서는 기본 600초로 기술(측정하지 않음). 재측정 필요.
- `plugin_hooks=removed`의 의미: 확인된 범위는 **"0.159.2에서 이미 신뢰된 플러그인의 `SessionStart` hook은 실행된다"**뿐이다. 근거 rollout(`01a0f407-88c0…`, t1-userprompt 세션)에 `ponytail@ponytail` SessionStart 주입 결과가 있다. 플러그인 `UserPromptSubmit` hook의 실행, 신규 설치 후 신뢰 절차는 이 증거로 판단할 수 없다. 공식 문서는 "플러그인 설치·활성화가 hook을 자동 신뢰하지는 않는다"고 명시.
- trust 우회의 영향: 이번 결과는 `--dangerously-bypass-hook-trust`와 `permission_mode: bypassPermissions` 조건에서 얻었다. 실제 설치 환경(기본 승인·샌드박스 모드, 신뢰 절차)에서의 동작은 별도 확인이 필요하다.
- **미수행**: 이 프로젝트의 신규 플러그인을 설치해 `UserPromptSubmit` hook이 플러그인 경로에서 도는지 — 전역 설치 필요, 사용자 승인 대기. 실행할 명령: `codex plugin marketplace add <로컬 마켓플레이스 경로>` → `codex plugin add <plugin>@<marketplace>` → 세션에서 `/hooks`로 hook 검토·신뢰.

**근거** (로그 경로, 트랜스크립트 발췌)

- `spikes/phase0/fixture/.codex/hooks.json`, `.codex/hooks/log_hook.py`
- `spikes/phase0/evidence/t1-userprompt.jsonl`(플래그 없음: hook 미실행), `t1a-question.jsonl`, `t1b-devtask.jsonl`
- hook 입력 원문: `spikes/phase0/evidence/t3f-hook-log.jsonl`의 `UserPromptSubmit` 행
- timeout: `evidence/timing.txt`, `t5a-hooktimeout.jsonl`, `t5b-hookdefaulttimeout.jsonl`, `slow-hook.log` — 설정 파일과 timeout 실행 로그가 없어 결론을 뒷받침하지 못함
- 플러그인 hook 간접 증거: `~/.codex/sessions/2026/10/01/rollout-2026-10-01T05-35-29-01a0f407-88c0-7c32-bbaf-7e61ff57b032.jsonl`(`PONYTAIL MODE ACTIVE` 포함, 개인 세션 파일이라 복사하지 않음)

---

## 2. 단계별 모델·effort 실제 적용

**확인 방법**

- 서로 다른 모델·effort를 지정한 subagent 2개를 정의한다(예: economy/medium, frontier/high).
- 각각 호출하고 실제 실행 모델과 effort를 확인한다.
- 지원하지 않는 effort를 지정했을 때 동작도 확인한다.

**확인 기준**

- 트랜스크립트·로그·사용량 기록에서 실제 모델명과 effort가 지정값과 일치하는가
- 미지원 effort 지정 시 오류 / 무시 / 대체 중 어떤 동작인가
- 플러그인에 포함된 subagent 정의가 사용자 설치만으로 인식되는가

**결과**

| subagent | 지정 모델 | 지정 effort | 실제 모델 | 실제 effort | 확인 출처 |
|---|---|---|---|---|---|
| mer-econ-medium (`.codex/agents/*.toml`) | gpt-6-luna | medium | gpt-6-luna | medium | `t2-spawn.rollout.txt` 자식 `turn_context` |
| mer-front-high | gpt-6-sol | high | gpt-6-sol | high | `t2b-front.rollout.txt` |
| mer-bad-ultra | gpt-6-luna | ultra(luna 미지원) | (생성 안 됨) | - | `t2c-badultra.rollout.txt` |
| mer-bad-turbo | gpt-6-luna | turbo(존재하지 않는 값) | (생성 안 됨) | - | `t2d-badturbo.jsonl` |

- 부모 세션은 모두 `gpt-6-luna`/`low`였고, 자식은 agent TOML의 값으로 실행됐다. `fork_turns` 기본값(all, 부모 대화 복제)에서도 agent_type의 model·effort는 적용됐다(`t2-spawn`).
- 미지원 effort는 **무시·대체 없이 spawn 호출이 오류로 실패**한다: ``Reasoning effort `ultra` is not supported for model `gpt-6-luna`. Supported reasoning efforts: low, medium, high, xhigh, max``. 오류 텍스트에 모델별 지원 목록이 포함되므로 Router가 재시도·강등 로직에 쓸 수 있다. 오류는 agent TOML 로딩 시점이 아니라 spawn 시점에 발생했다.
- 모델별 지원 effort(`~/.codex/models_cache.json`, 읽기 전용): gpt-6-luna = low/medium/high/xhigh/max, gpt-6-sol·gpt-6.1-sol = 위 + ultra, gpt-5.5 = low~xhigh. Effort Map(§12)은 모델별 지원 목록을 전제해야 한다.
- 프로젝트 `.codex/agents/*.toml`은 별도 설정 없이 인식됐다(`name`/`description`/`developer_instructions` + 선택 `model`/`model_reasoning_effort`).
- **미수행**: 플러그인에 동봉한 agent 정의의 인식 여부. 공식 플러그인 문서의 번들 대상은 skills·MCP·hooks·브라우저 확장이며 agents는 언급이 없다. 기존 프로젝트(`model-effort-router`) README도 "현재 Codex 표면이 플러그인 agent를 인식하지 않을 수 있다"고 전제한다. 전역 설치가 필요해 검증하지 못했다. 설치 후 확인 명령: `codex plugin add <plugin>@<marketplace>` 후 `codex exec "agent_type=<plugin agent>로 spawn_agent"`.

**근거** (로그 경로, 트랜스크립트 발췌)

- `spikes/phase0/fixture/.codex/agents/mer-*.toml`
- rollout 요약(`spikes/phase0/rollout_summary.py`, `collect.sh`로 생성): `evidence/t2-spawn.rollout.txt`, `t2b-front.rollout.txt`, `t2c-badultra.rollout.txt`, `t3c-dynbad.rollout.txt`
- 오류 텍스트: `t2c-badultra.rollout.txt`의 `function_call_output`, `t2d-badturbo.jsonl`
- 원본 rollout은 `~/.codex/sessions/2026/10/01/`(개인 세션 파일, 복사하지 않음)

---

## 3. 동적 지정 vs 사전 정의 조합

**확인 방법**

- subagent 호출 시점에 모델·effort를 인자로 넘기는 방법이 있는지 확인한다.
- 없다면 subagent 정의 파일을 여러 개 두고 이름으로 선택하는 방식을 확인한다.

**확인 기준**

- 동적 지정 가능 여부
- 불가능하면: 조합 정의 파일 개수 제한, 로딩 시점(설치 시 / 세션 시작 시 / 호출 시)
- hook에서 subagent 호출을 가로채 검증·차단할 수 있는가

**결과**

- 결론: **둘 다 가능** (`동적 지정` 주 경로 + `사전 정의 조합` 폴백)

1. **동적 지정 가능.** `spawn_agent`(네임스페이스 `collaboration`) 인자: `task_name`, `message`, `agent_type`, `fork_turns`, `model`, `reasoning_effort`. `model="gpt-6-sol", reasoning_effort="high"`로 spawn하자 자식 `turn_context`가 sol/high로 기록됨(`t3a-dynamic`).
2. **제약(툴 안내문 기반, 실험 미검증)**: 툴 안내문은 `fork_turns`가 생략되거나 `"all"`이면 부모 모델·effort를 상속한다고 설명한다. `fork_turns=all`과 호출 시점 `model`·`reasoning_effort`를 함께 넘긴 실험은 없어 "무시"인지 "오류"인지 모른다. 반면 `agent_type`(TOML)의 model·effort는 `fork_turns=all`에서도 적용됐다(`t2-spawn`).
   - 툴 안내문은 모델에게 "사용자·AGENTS.md·skill이 요청할 때만 model/effort를 지정하라"고 지시한다. 따라서 동적 경로를 쓰려면 skill 지침이나 `PreToolUse` 강제가 필요하다.
3. 잘못된 effort를 동적 인자로 넘겨도 동일하게 spawn 오류(`t3c-dynbad`).
4. **hook이 spawn을 가로채 검증·차단·재작성 가능.** `PreToolUse`(matcher `.*`)에 `tool_name="collaborationspawn_agent"`와 `tool_input`(model, reasoning_effort 포함; `message`는 암호화된 문자열)이 전달된다.
   - 차단: `permissionDecision:"deny"` → 모델에 `Tool call blocked by PreToolUse hook: <사유>`가 반환되고 자식은 생성되지 않음(`t3d-deny`).
   - 재작성: `permissionDecision:"allow"` + `updatedInput`으로 `reasoning_effort` low→xhigh를 바꾸자 자식이 sol/**xhigh**로 실행됨(`t3e-rewrite`, `t3f-hooklog`). 확인한 것은 **기존 필드 값 변경**뿐이며, model·effort 필드 추가나 `fork_turns` 변경은 미검증. `updatedInput`은 문서 외 동작이다.
   - `SubagentStart`/`SubagentStop` hook도 호출됨(필드: `agent_id`, `agent_type`, `model`, `last_assistant_message` 등). 동적 spawn의 `agent_type`은 `default`.
5. 사전 정의 파일 방식: 프로젝트 `.codex/agents/*.toml` 4개(오류용 2개 포함)가 모두 인식됨. 개수 제한은 검증하지 않음(사용자 설정의 `agents.max_threads=6`, `max_depth=1`은 동시 실행·중첩 깊이 제한이며 정의 개수 제한이 아님).
6. 로딩 시점(설치 시/세션 시작/호출 시)은 매 실행이 새 프로세스라 구분하지 못했다(미검증).

**근거** (로그 경로, 트랜스크립트 발췌)

- `spikes/phase0/evidence/t3a-dynamic.rollout.txt`(spawn 인자 `model`,`reasoning_effort`, 자식 sol/high), `t3c-dynbad.rollout.txt`
- `t3d-deny.jsonl`/`t3d-deny.rollout.txt`(차단 문구), `t3e-rewrite.rollout.txt`, `t3f-hooklog.rollout.txt`(재작성 후 sol/xhigh)
- hook 입출력: `evidence/t3f-hook-log.jsonl`; hook 코드 `fixture/.codex/hooks/pretool.py`, 설정 `spikes/phase0/fixture-hooks.full.json.txt`
- spawn_agent 안내문(fork 제약): `evidence/prompt-input.json`의 `multi_agent_role` 블록

**기획서 반영**: §3.2 표, §12, §23 `agents/`

---

## 4. 단계 간 컨텍스트 전달

**확인 방법**

- Plan subagent → Implement subagent → 테스트 명령 → Review subagent 순서로 수동 실행한다.
- 각 단계 출력을 다음 단계 입력으로 넘긴다.

**확인 기준**

- subagent 결과가 메인 세션으로 어떤 형태(전문 / 요약)로 돌아오는가
- 변경 diff를 Review subagent에 넘길 수 있는가(파일 경로 참조 / 본문 전달)
- Review subagent가 Implement 대화 기록을 이어받지 않는가(별도 컨텍스트)
- 전달 크기 제한이 있는가

**결과**

테스트 방식(`t4-pipeline`, 1회 실행, `q4-prompt.txt`): 부모(luna/low)가 plan → impl → 테스트 → review를 오케스트레이션. fixture는 `mul`이 없어 `test_calc.py`가 실패하는 작은 저장소.

| 확인 | 결과 |
|---|---|
| subagent 결과 형태 | 전문이 부모에게 `Message Type: FINAL_ANSWER / Sender: /root/<task_name> / Payload: <전문>` 형태의 agent 메시지로 전달됨. plan 결과 1,896자(마커 + FILLER 150줄)가 잘리지 않고 도착(부모가 FILLER_COUNT=150, 마커 확인). 요약되지 않음. 크기 제한은 이 범위에서 발견되지 않음(더 큰 출력은 미검증). |
| Plan → Implement | 부모가 plan 3줄을 implement의 `message`에 그대로 전달 → `calc.py`에 `mul` 추가 |
| 테스트 | 부모가 자신의 셸 툴로 `python3 -m unittest -v`와 `git diff` 실행(결정적 테스트 게이트 가능) |
| diff + 테스트 결과 → Review | 본문 전달. 리뷰어 응답 `VERDICT=ok` |
| Review의 대화 격리 | `fork_turns="none"` 리뷰어: `CONTEXT=NO_MARKERS`(impl 종료 마커 `IMPL-MARKER-Z9`, plan 마커 `PLAN-MARKER-X1`을 보지 못함). `fork_turns` 생략(기본 all) 리뷰어: `SEES_IMPL_MARKER`(부모 대화 전체를 복제) |
| 파일 경로 참조 | 모든 agent가 같은 cwd·파일시스템을 공유하므로 diff를 파일로 써 두고 경로만 넘기는 방식도 가능(이번에는 본문 전달만 측정) |

- 모든 자식이 별도 rollout을 가지며 `agent_path=/root/<task_name>`, `parent_thread_id`로 연결된다.
- 비용 참고: 이 실행의 부모 기준 사용량은 입력 384,934(캐시 374,784) / 출력 1,085 토큰. 자식 사용량은 `codex exec --json`에 별도로 나오지 않았다.
- 한계: 오케스트레이터가 모델(luna)이고 프롬프트로 단계를 고정했다. Router가 오케스트레이터가 되는 구조(§3.1)에서 지시 이탈 빈도는 1회 실행으로 판단할 수 없다.
- 한계: "전문 반환"은 1,896자까지만 확인했다(실제 diff는 더 클 수 있음, 50KB 이상 미검증). Review 격리(`NO_MARKERS`)는 리뷰어 모델의 자기 보고이며 자식 rollout의 입력 내용을 직접 확인하지 않았다.

**근거** (로그 경로, 트랜스크립트 발췌)

- `spikes/phase0/q4-prompt.txt`, `evidence/t4-pipeline.jsonl`, `evidence/t4-pipeline.rollout.txt`
- FINAL_ANSWER 길이(plan 1,896 / impl 122 / review 181·194자)는 rollout의 `agent_message`(`author=/root/plan` 등)에서 계산
- 최종 부모 응답: `FILLER_COUNT=150, PLAN_MARKER=yes / CONTEXT=NO_MARKERS; VERDICT=ok ... / FORKED CONTEXT=SEES_IMPL_MARKER; VERDICT=ok ...`
- fixture 변경 결과: `spikes/phase0/fixture/calc.py`(`mul` 추가, 미커밋 상태)

**기획서 반영**: §16, §17

---

## 5. 구독 인증, timeout·취소·fallback

**확인 방법**

- API 키 환경 변수 없이 구독 로그인 상태로만 1~4를 실행한다.
- subagent 실행 중 사용자 취소를 한다.
- hook이 timeout을 넘기도록 지연시킨다.

**확인 기준**

- API 키 없이 모든 단계가 동작하는가
- 취소 후 재요청 시 같은 단계가 중복 실행되지 않는가
- hook timeout 초과 시 요청이 차단되는가, 그냥 진행되는가
- 진행된다면 Router 없이 기본 동작으로 떨어지는가

**결과**

- **구독 인증**: 모든 `codex exec` 호출이 성공했다. 실행 당시 `codex login status` = `Logged in using ChatGPT`, API 키 환경 변수 0개로 확인했으나 **출력은 evidence에 보존되지 않았다**(인증 파일은 열람·복사하지 않음). 구독 플랜 등급은 확인하지 못했다.
- **hook timeout 초과 (`t5a-hooktimeout`) — 관찰됨, 증거 미보존**: timeout=2초, 6초 sleep hook 설정에서 요청이 차단되지 않고 정상 응답("Six")을 받은 것으로 관찰됐다(fail-open). 그러나 t5a 설정과 `slow-hook.log`의 해당 실행 기록이 덮어써졌고, t5a와 t5b의 jsonl이 사실상 동일해 hook 종료 여부를 저장된 증거로 구분할 수 없다. 재측정 필요.
- **취소 (`t5c-cancel`) — 관찰됨, 증거 미보존**: subagent가 `sleep 40` 셸을 실행 중일 때 `SIGINT`를 보냈고, 실행 당시 exec·자식 셸 프로세스가 사라지고 완료 표식 파일이 생기지 않은 것으로 관찰됐다. 그러나 ps 출력과 표식 파일 확인 결과는 저장되지 않았고, 자식 rollout에는 TURN_CONTEXT만 있어 `sleep 40` 실행 기록이 없다. `t5c-cancel.stderr`에는 `UnknownProcessId`와 "failed to record rollout items" 오류가 있다. t5c는 `timing.txt`에도 없다. 재측정 필요.
- **중복 실행**: 취소 후 같은 요청을 재제출했을 때 단계가 중복 실행되는지, hook timeout 후 fallback 경로에서 Router가 두 번 실행되는지는 **미수행** — Router Core가 아직 없어 검증 대상이 없다. Phase 3에서 요청 ID/멱등 키와 함께 재검증 필요.
- 유의: 이번 hook·agent 설정은 모두 프로젝트 로컬이다. 플러그인 설치 경로(전역)에서의 위 동작은 미검증.

**근거** (로그 경로, 트랜스크립트 발췌)

- `evidence/slow-hook.log`(마지막 실행 1건만 남음, timeout=2 실행 기록 없음), `evidence/t5a-hooktimeout.jsonl`, `evidence/timing.txt`(t5a 6.5s), 코드 `fixture/.codex/hooks/slow.py`
- `evidence/t5c-cancel.jsonl`, `t5c-cancel.stderr`, `t5c-cancel.rollout.txt`(`aborted by user after 13.4s`)
- 인증: 보존된 증거 없음

**기획서 반영**: §9, §19

---

## 6. 구독 모델 분류 호출

**확인 방법**

- hook 또는 Router에서 economy tier 모델로 L1~L5 분류 프롬프트를 실행한다.
- 작업 5건(L1~L5 각 1건)으로 지연과 사용량을 측정한다.

**확인 기준**

- 플러그인 컨텍스트에서 구독 인증으로 호출 가능한가
- 호출 방식(subagent / CLI 하위 프로세스 / 기타)
- 건당 지연(p50, 최대)이 hook timeout 안에 들어오는가
- 건당 사용량

**결과**

호출 방식: `codex exec --json --ephemeral -s read-only -m gpt-6-luna -c model_reasoning_effort=low`를 **하위 프로세스**로 실행(`spikes/phase0/classify.py`). hook 재귀를 피하려고 `.codex/`가 없는 디렉터리(`classifier-cwd`)에서 실행. 구독 인증만 사용.

| 작업 | 기대 레벨 | 분류 결과 | 지연 | 사용량 |
|---|---|---|---|---|
| README 오타 수정 | L1 | L1 | 4.13s | 입력 29,757(캐시 6,912) / 출력 20 |
| parseConfig null 체크 | L2 | L2 | 4.02s | 입력 29,767(캐시 3,840) / 출력 20 |
| 주문 이력 REST 엔드포인트 + 테스트 | L3 | L3 | 3.76s | 입력 29,768(캐시 0) / 출력 18 |
| 결제 모듈 재시도 로직 공통화 리팩터링 | L4 | L4 | 4.07s | 입력 29,776(캐시 18,176) / 출력 22 |
| 플러그인 아키텍처 설계·구현·마이그레이션 | L5 | L5 | 5.56s | 입력 29,788(캐시 0) / 출력 20 |

- 지연 p50 4.07s, 최대 5.56s(n=5, 각 1회, 표본이 작음). 5건 모두 기대 레벨이 나왔지만 작업 문장이 루브릭 단어를 그대로 담고 있어(예: "multi-file … with tests") **분류 정확도에 대한 증거로 쓸 수 없다**. 정확도는 모호한 작업을 포함한 20건 이상 블라인드 세트로 §22에서 측정한다.
- 실행 조건: 프로젝트 로컬 hook, trust 우회, `permission_mode: bypassPermissions`. §8.1이 요구하는 플러그인 컨텍스트가 아니다.
- 재귀 방지: 이번 방지책은 `.codex/`가 없는 cwd뿐이다. 플러그인·전역 hook(예: 이미 신뢰된 ponytail의 `user_prompt_submit`)은 cwd와 무관하게 중첩 `codex exec`에서도 실행되므로, Router hook이 플러그인으로 배포되면 재귀한다. 미검증.
- **hook 안에서 호출 (`t6-hookclassify`)**: `UserPromptSubmit` hook이 위 함수를 호출해 분류하고 결과를 `additionalContext`로 주입. 분류 4.57s(`classify-hook.log`), 전체 요청 9.9s(메인 모델 gpt-6-sol/low 포함). 모델 응답에 분류 결과가 반영됨. 구독 인증은 하위 프로세스가 그대로 상속했다. 이 실행의 hook 설정(timeout=30)은 보존되지 않았다.
- 사용량: 출력은 약 20토큰이지만 **입력이 호출당 약 29.8k 토큰**으로 고정 오버헤드가 크다. 이 값은 이 환경 기준이다(사용자 AGENTS.md, ponytail 등 전역 주입 포함). `--ignore-user-config`를 주면 27.1k / 3.4s로 소폭 감소(`evidence/classify-ignore-user-config.txt`). 캐시 적중분은 호출마다 달라 일정하지 않다. 구독 한도 차감 기준의 비용은 측정하지 못했다(토큰 수만 기록).
- **비용 판단**: 분류 1회 입력(약 29.8k)이 사소한 작업 1턴 전체(t1: 29,986)와 비슷하다. §8.1 전제 3("분류 호출 사용량이 절감 효과를 상쇄하지 않는가")은 해소되지 않았고, L1/L2에서는 상쇄 가능성이 높다.
- hook timeout 설계: 4~6초 지연이므로 hook timeout은 10초 이상이 필요하다. 추가 지연은 **라우팅 대상 요청에만** 발생한다(§3.3에서 대화·단순 질문은 제외). Backend `timeout_s`는 hook timeout보다 작아야 한다. hook이 먼저 종료되면 fail-open으로 Router 없이 진행돼 §9의 L3 기본 결정이 적용되지 않는다. §22.3 절감 효과 계산에 이 고정 입력량(약 30k)을 넣어야 한다.

**근거** (로그 경로, 트랜스크립트 발췌)

- `spikes/phase0/classify.py`, `tasks.txt`, `evidence/classify-results.jsonl`(원본 JSON), `evidence/classify-hook.log`, `evidence/t6-hookclassify.jsonl`, `fixture/.codex/hooks/classify_hook.py`

**기획서 반영**: §8.1, §24 Phase 1 Backend 선택

---

## 발견 사항

1. **hook 신뢰(trust)가 필수.** 프로젝트 로컬 hook은 신뢰된 `.codex/` 계층 + hook별 검토(`/hooks`, `~/.codex/config.toml [hooks.state]`의 `trusted_hash`)가 있어야 돈다. 미신뢰면 **오류 없이 조용히 건너뛴다**(`t1-userprompt`). 플러그인 hook도 설치만으로 신뢰되지 않는다(문서). 이번 스파이크는 호출 단위 플래그 `--dangerously-bypass-hook-trust`로 우회했다. Router는 "hook 미신뢰 → Router 비활성" 상태를 사용자에게 알려야 한다.
2. **`spawn_agent`의 `fork_turns` 기본값이 `all`** 이다. 툴 안내문에 따르면 이때 호출 시점 model·effort override가 적용되지 않는다(실험 미검증). 기본값으로 호출하면 Review가 Implement 대화를 그대로 본다(`t4`에서 확인). Router는 항상 `fork_turns="none"`(또는 정수)을 지정해야 한다.
3. **hook의 `tool_name`은 `collaborationspawn_agent`**(네임스페이스와 이름이 구분자 없이 이어진 형태). 문서는 matcher를 `Agent`로 설명하지만 이번에는 `.*`만 사용했고 `Agent` matcher는 검증하지 않았다. `message`는 rollout·hook 입력 모두에서 암호화된 문자열이라 hook이 본문 내용을 검사할 수 없다(model·effort·agent_type·fork_turns 등 메타데이터는 읽힘).
4. **`PreToolUse`의 `updatedInput`으로 spawn 인자를 재작성할 수 있다** — 이번에 문서 외 실험으로 확인한 동작이며 버전 의존 가능성이 크다(0.159.2에서만 확인).
5. **미지원 effort는 spawn 오류**(무시·대체 아님). 모델별 지원 effort가 다르다(luna에는 `ultra` 없음).
6. 사용자 전역 설정에 `agents.max_threads=6`, `max_depth=1`이 있다(Router가 중첩 spawn을 전제하면 안 됨). 툴 안내문은 동시 슬롯 7개를 표시.
7. **분류 호출의 고정 입력량이 약 29.8k 토큰**, 호출당 지연 4~6초. `--ignore-user-config` 등 경량화 효과는 작다.
8. **Codex가 `~/.codex/config.toml`에 fixture 프로젝트의 `trust_level="trusted"` 항목을 스스로 추가했다**(`-c projects.<path>.trust_level="trusted"` 값이 영속화된 것으로 보임; 이전 실험들의 항목도 동일 패턴으로 누적돼 있음). 수행자가 직접 편집한 것은 아니지만 전역 설정 파일이 바뀌었으므로, 원치 않으면 `[projects."…/spikes/phase0/fixture"]` 블록을 사용자가 삭제할 것.
9. `~/.codex/config.toml`의 `persistent_instructions`가 0.159.2에서 무시된다는 경고가 매 실행의 `--json` 출력에 `type:"error"` 항목으로 섞여 나온다 → Router의 exec 출력 파서는 이를 무시해야 함.
10. `codex exec`는 stdin이 파이프이면 EOF까지 대기한다(첫 시도가 120초 이상 멈춤). 하위 프로세스 호출 시 `stdin=DEVNULL` 필수.
11. 플러그인 동봉 agent는 공식 플러그인 문서의 번들 대상에 없다. 사용하려면 플러그인 설치 단계에서 프로젝트 `.codex/agents/`나 `[agents.<name>] config_file=`로 배치하는 별도 절차가 필요할 가능성이 높다(미검증).
12. **증거 보존 한계**. 아래 결론은 원본 증거가 사라졌거나 저장되지 않아 저장된 파일로 재확인할 수 없다.
    - hook-log 초기화: t1a, t1b, t3d, t3e의 hook 입출력 원문(남은 것은 `t3f-hook-log.jsonl`뿐)
    - `slow-hook.log` 덮어씀: t5a의 timeout 종료 기록
    - `hooks.json` 교체: t1, t5a, t5b, t6의 hook 설정(현재 파일은 `fixture-hooks.full.json.txt`와 동일하고 slow.py 항목이 없음)
    - t5b jsonl 덮어씀: 첫 실행(6.1s)
    - 저장되지 않음: t5b·t2d rollout, `codex login status` 출력, t5c의 ps·표식 파일 확인 결과
13. **분류기 재귀 위험**: 분류용 중첩 `codex exec`의 재귀 방지는 `.codex/` 없는 cwd뿐이다. 플러그인·전역 hook은 cwd와 무관하게 실행되므로, Router hook을 플러그인으로 배포하면 분류 호출에서 Router hook이 다시 실행된다. 환경 변수 가드 등이 필요하다.
14. **자식 사용량 미노출**: `codex exec --json`은 subagent 사용량을 보고하지 않는다. §22.3 "모든 subagent 합산"은 rollout의 `token_count` 이벤트를 모아 계산해야 한다. t4 부모 입력 약 385k를 오케스트레이션 비용의 첫 기준값으로 기록한다.

## 기획서 갱신 목록

| 기획서 절 | 변경 내용 | 반영 여부 |
|---|---|---|
| §3.2 표 | 행별 상태 갱신: `UserPromptSubmit`=동작 확인(프로젝트 로컬, trust 우회; 플러그인 경로는 설치 후 재확인), subagent `model`/`reasoning_effort`=확인, **동적 지정=가능(`fork_turns=none`에서 확인; `all`일 때 무시된다는 것은 툴 안내문 근거·실험 미검증)**, spawn 가로채기=`PreToolUse` 차단 확인, `updatedInput` 재작성은 문서 외 동작·기존 필드 변경만 확인. | 미반영 |
| §3.2 하단 | "동적 지정이 불가능한 경우" 조합 사전 정의 문단을 **폴백**으로 격하. `mer-plan-frontier-high` 식 조합 파일은 기본 경로가 아님. 플러그인 동봉 agent 인식은 미검증이라 명시. | 미반영 |
| §3.7 / §9 | hook 신뢰(trust) 요건 추가: 미신뢰 시 Router가 조용히 비활성됨 → 온보딩에 `/hooks` 검토 단계와 미신뢰 감지 안내. **플러그인 업데이트 후 재신뢰** 절차 필요(hash 변경 시 조용히 꺼질 가능성). hook timeout 초과는 fail-open으로 관찰됨(증거 미보존, 재측정 필요). | 미반영 |
| §9 | Backend `timeout_s`는 hook timeout보다 작아야 한다. hook이 먼저 종료되면 fail-open으로 L3 기본 결정이 적용되지 않는다. 현재 §9 `timeout_s: 10`과 hook timeout 권장값(10초 이상)이 겹치므로 둘을 함께 정한다. | 미반영 |
| §8.1 / §3.7 | 분류용 중첩 `codex exec`의 **재귀 방지 가드**(환경 변수 등) 추가. cwd 분리만으로는 플러그인·전역 hook 재귀를 막지 못한다. | 미반영 |
| §21 / §22.3 | 자식 사용량은 `exec --json`에 없으므로 rollout `token_count` 이벤트로 합산하는 방법 명시. t4 부모 입력 약 385k를 오케스트레이션 비용 기준값으로 기록. 분류 1회 약 29.8k 입력이 L1/L2 절감분을 상쇄할 수 있다는 위험 명시. | 미반영 |
| §8.1 | 분류 호출 방식 후보를 `codex exec` 하위 프로세스(luna/low, stdin DEVNULL, `--ephemeral`, 재귀 가드)로 구체화. 지연 4~6초, 호출당 입력 약 29.8k 토큰(이 환경 기준). 전제 3항목 중 "구독 인증 가능"·"timeout 안 완료"는 프로젝트 로컬 조건에서만 확인, 플러그인 컨텍스트는 미확인. "절감 효과 상쇄 여부"는 미해소. | 미반영 |
| §12 | Effort Map에 모델별 지원 effort 표 추가(luna: low~max, sol: +ultra). 미지원 값은 spawn 오류이므로 Map 생성 시 검증한다. "오류 메시지 기반 강등"은 기획서의 "가장 가까운 상위값" 규칙과 충돌하므로 채택하지 않는다. 현재 추상 effort(medium/high/xhigh)는 luna·sol 모두 지원하므로 당장 대체 규칙이 발동할 일은 없다. | 미반영 |
| §16 / §17 | 결과가 전문으로 반환됨을 전제로 명시. Review는 `fork_turns="none"` + diff·테스트 결과 본문 전달(또는 공유 cwd 파일 경로). 기본 `fork_turns`(all)는 격리가 깨지므로 금지. | 미반영 |
| §19 | 취소 시 subagent·하위 프로세스는 함께 종료됨(확인). 중복 실행 방지는 미검증이므로 요청 ID 기반 멱등 처리와 Phase 3 재검증 항목 추가. | 미반영 |
| §23 `agents/` | 플러그인 번들에 `agents/`를 기본 경로로 가정하지 말 것. 동적 spawn을 기본으로 하고, 정적 agent 파일은 배치 방식 확인 후 결정. | 미반영 |
| §24 Phase 0 | 추가 확인 항목을 분리(모두 live 실행 필요, **사용자 승인 전 실행 금지**): (a) 플러그인 경로 `UserPromptSubmit` hook·agent 인식(신규 전역 설치 또는 이미 설치된 `model-effort@model-effort-router-bundle` 활용 검토), (b) 플러그인 hook 상태에서 분류 호출 재귀 여부, (c) 기본 승인·샌드박스 모드에서 hook·중첩 exec 동작, (d) `fork_turns=all` + 호출 시점 model/effort, `updatedInput`의 필드 추가·`fork_turns` 변경, (e) t5a/t5b/t5c 재측정(설정·로그·ps·rollout 보존), (f) 50KB 이상 결과 전달, (g) 20건 이상 블라인드 세트로 분류 정확도·분산, (h) 취소 후 재요청 중복 실행. | 미반영 |
| §26 미결 사항 | `updatedInput`·`tool_name` 형식의 버전 의존성, 구독 플랜별 한도, hook 안 분류 호출의 사용량 차감 방식 추가. | 미반영 |

## 다음 단계

- 종합 판정이 `진행`이면: Phase 1~3 구현 계획서(`docs/plans/phase1-3-implementation.md`) 작성
- `설계 수정 후 진행`이면: 기획서 갱신 후 구현 계획서 작성
- `§2 재검토`면: 대안 제품 형태 검토

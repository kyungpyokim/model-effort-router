# 평가 도구 사용법

모든 도구는 저장소 루트에서 Python 3 표준 라이브러리만으로 실행한다. 평가 코드는 `evaluation/`(플러그인 번들에 포함되지 않음)에 있다.

**중요: 모델을 호출하는 경로는 전부 `--live`가 있어야 실행된다. live 실행은 구독 사용량을 소모하므로 사용자의 명시적 결정이 있을 때만 실행한다. 테스트와 dry-run은 모델을 호출하지 않는다.**

| 도구 | 기본(모델 호출 없음) | `--live` |
|---|---|---|
| 코퍼스 검증과 라벨러 일치율 | `python3 -m evaluation.cases evaluation/corpus/seed.jsonl` | 해당 없음 |
| Backend 비교 | `python3 -m evaluation.compare --corpus C.jsonl --backends NAME --dry-run` (fake/등록된 오프라인 Backend는 `--live` 없이 실행) | `subscription`·`jev`·`nimble` Backend는 `--live` 필요(nimble은 로컬 Ollama 호출이라 과금은 없고, 작업 디렉터리의 `difficulty.nimble` 설정을 mer처럼 적용한다; `ollama pull nimble` 필요, 임계값은 Jev 값을 빌려 쓰므로 이 비교로 보정한다). subscription은 케이스당 `codex exec` 1회(입력 약 29.8k 토큰, `no_route` 케이스도 실행), jev는 케이스당 외부 API 1회(약 600 토큰, 텍스트가 TypeSafe로 전송됨) |
| 비용 기준선 실행 | `python3 -m evaluation.live_runner --cases C.jsonl --fixture DIR --out runs.jsonl` (실행 계획만 출력) | `--live`를 붙이면 케이스마다 baseline과 router 두 번 `codex exec` 실행 |
| 기준선 비교 보고 | `python3 -m evaluation.baseline report runs.jsonl --md out.md --json out.json` | 해당 없음 (기록 파일만 읽음) |
| 요구사항 충족 기록 | `python3 -m evaluation.baseline mark runs.jsonl CASE_ID baseline\|router yes\|no [--run K]` | 해당 없음 (수동 판단) |

## 순서

1. `docs/evaluation/labeling-guide.md`대로 `seed.jsonl`의 draft를 독립 라벨링하고 새 코퍼스 파일(`evaluation/corpus/*.jsonl`)에 `labeled` → `adjudicated`로 옮긴다. `seed.jsonl`의 `proposed`는 정답이 아니다.
2. `evaluation.cases`로 일치 확인. `discuss`는 합의, `revise_guide`는 가이드 보완 후 재라벨.
3. `evaluation.compare`로 Backend 비교(exact, ±1, over/under, critical miss, latency, 토큰, fallback, 세션 프로필 일치, **target 정확도**). Backend는 `no_route` 케이스를 포함해 모든 adjudicated 케이스에 실행하고(target을 전부에서 채점), level·위험 플래그는 level이 있는 케이스에서만 채점한다. `target (backend)` 열은 Backend가 정한 target(없으면 규칙)이 라벨과 맞은 비율이고, 예측에는 `target`/`target_source`가 남는다. 보고서 첫 줄은 규칙 기반 target 정확도를 경로 포함과 텍스트만(hook이 보는 입력) 두 가지로 보인다.
4. 비용 기준선: fixture 저장소를 준비하고 `live_runner`로 실행. router 모드는 `mer` CLI(`python3 -m model_effort_router.cli run`)를 돌린다. 실행마다 fixture를 eval workdir에 복사하고 git 저장소로 만든 뒤(고정 identity, 커밋 1개), 끝나면 diff를 저장하고 workdir을 비운다. 끝난 뒤 `mark`로 요구사항 충족 여부를 사람이 기록하고 `baseline report`로 판정한다.

## 판정 규칙 (§22.3)

Router가 품질을 유지하면서 전체 사용량(구현 세션 + 독립 Review 세션 + 분류 호출)을 줄이지 못하면 기본 모드를 `auto`로 두지 않는다. 보고서의 `decision.verdict`는 `auto_allowed`, `do_not_default_to_auto`, `insufficient_data`(짝이 없거나 `requirements_met` 미기록) 중 하나다.

## live_runner 사전 조건 (직접 해야 함)

- **router 모드는 플러그인이 필요 없다.** `mer`가 판정, 세션 실행, Test Gate, 승격, 독립 Review를 직접 하고, 시작하는 codex 세션에는 `MER_CLASSIFIER=1`을 줘서 설치된 플러그인 hook이 아무것도 하지 않게 한다. router 기록은 mer 로그에 `route`와 `session_start` 이벤트가 있을 때만 `router_active: true`이고, 아니면 보고서에서 제외된다.
- 플러그인이 전역 설치되어 있으면 baseline 실행도 라우팅될 수 있다. baseline에서 router 활동(route 이벤트 또는 `mer_` subagent rollout)이 보이면 `contaminated: true`로 기록되고 보고서에서 제외된다.
- 실행은 **고정된 eval workdir 하나**(`--workdir`, 기본 `<state dir>/eval-workdir`, realpath)를 매번 지우고 fixture로 다시 채워 쓴다. Codex가 이 경로에 대해 `~/.codex/config.toml`에 `trust_level` 항목을 **하나 영구 저장**한다. 끝나면 직접 지워도 된다. 도구는 workdir이 없거나 자신이 만든 마커 파일(`.mer-eval-workdir`)이 있을 때만 내용을 지운다. 마커 없는 기존 디렉터리, fixture와 같거나 그 안팎인 경로, 현재 디렉터리·홈·루트(또는 그 상위)는 아무것도 지우지 않고 거부한다(종료 코드 1).
- 케이스 하나가 실패하면 `error`가 있는 기록(gate `incomplete`)을 남기고 다음 케이스로 계속한다. 이런 기록이 있으면 판정은 `insufficient_data`다.
- 실행 후 `<out 파일명에서 .jsonl을 뺀 경로>-diffs/<case>.<mode>.r<run>.diff`에 변경 전체(`git diff`, 새 파일 포함)와 `# untracked:` 목록이 저장되고 기록의 `diff_path`에 경로가 남는다. `requirements_met`은 이 diff를 보고 사람이 `mark`로 기록한다.
- router 기록에는 추가로 `level`, `session_profile`(시작), `final_profile`, `escalations`, `review_verdict`(`approved`/`changes_requested`/`unknown`), `review_findings`, `thread_ids`, `mer_status`가 남는다. `fix_rounds`는 승격 횟수다. `unknown`(파싱 불가 verdict)은 승인으로 치지 않는다.

## 알려진 한계

- 사용량은 rollout 파일의 `token_count` 이벤트에서 읽는다. router 모드는 mer가 보고한 thread id마다(구현 세션과 별도 root 세션인 Review 세션 포함) rollout을 찾고, thread별 누적값을 한 번만 센다. rollout이 없는 thread만 mer가 보고한 호출별 사용량(누적값의 차이)을 쓴다. `codex exec --json`의 `turn.completed.usage`는 resume 시 세션 누적값이라 스트림 합산은 thread별 최댓값을 쓴다. 이 이벤트의 형태 설명: 이 이벤트의 JSON 형태는 Codex 0.159.2 실제 rollout으로 확인했고 `evaluation/usage.py`의 `_token_count_total` 한 함수에 격리했다. rollout에 token_count가 없으면 0으로 치지 않고 `stages_without_usage`로 보고하며 판정은 `insufficient_data`가 된다. router 실행에서 측정된 사용량이 0이어도 마찬가지다(`no_usage_measured`).
- 분류 호출 사용량은 Backend가 보고한 실측값이다(`classifier_usage`를 route 이벤트에 기록, 호출이 실패한 경우 포함). 모델을 호출하는 Backend가 실행됐는데 사용량을 보고하지 않으면 route 이벤트에 `classifier_usage: null`을 명시하고(키 없음 = 모델 호출 없음 = 0), null이 있으면 추정하지 않고 실행을 `classifier_usage_missing`(불완전)로 표시한다. 종료 코드가 0이 아닌 호출의 사용량은 얻을 수 없다.
- rollout은 실행 시작 이후에 수정된 파일 중 첫 줄의 `session_id`가 일치하는 것만 읽는다.
- 전체 사용량은 `input + output` 토큰 합이다. 모델별 가중 비용은 계산하지 않는다.
- TODO(Phase 6): confidence 보정, cost와 로컬 자원 사용량 비교.

## Pilot (Baseline vs Router, 4 cases)

fixture `evaluation/pilot/fixture/`(작은 Python 상점 서비스, gate는 `python3 -m unittest`)와 `evaluation/pilot/cases.jsonl`(L1~L4, L4는 `auth`). 라벨은 파일럿 작성자가 정한 값이며 코퍼스 정답이 아니다. fixture는 git 저장소가 아니어도 된다(실행 시 workdir에 `git init`).

설정: baseline = `gpt-6-luna` / `high`. router 모드는 모델·effort를 mer가 레벨별로 정한다(기록의 `session_profile`, `final_profile`). 플러그인 설치와 hook 신뢰는 필요 없다.

사용자 승인 후 실행할 live 명령(구독 사용량 소모, codex exec 8회 이상(router는 승격·Review마다 추가)):

```
python3 -m evaluation.live_runner --cases evaluation/pilot/cases.jsonl --fixture evaluation/pilot/fixture --out runs/pilot-p7b.jsonl --baseline-model gpt-6-luna --baseline-effort high --router-backend jev --router-fallback subscription --repeat 2 --live
```

실행 후:
1. 케이스·모드별로 결과를 직접 확인하고 `python3 -m evaluation.baseline mark runs/pilot-p7b.jsonl CASE_ID baseline|router yes|no` (pilot-l1, pilot-l2, pilot-l3, pilot-l4-auth 각각 두 모드; `--repeat`로 여러 번 돌렸다면 `--run K`를 붙여 실행마다).
2. `python3 -m evaluation.baseline report runs/pilot-p7b.jsonl --md pilot.md --json pilot.json`

## 반복 실행과 router 분류기 (live_runner 옵션)

- `--repeat N`(기본 1): 케이스·모드마다 N번 실행하고 기록에 `run: 1..N`을 남긴다(순서: run → 케이스 → 모드). `run`이 없는 옛 기록은 run 1이다. `baseline report`는 `(case_id, run)`으로 baseline과 router를 짝짓고, 짝 단위 표 외에 케이스별 평균(`per_case_mean`)과 전체 합계를 낸다. `mark`는 같은 케이스·모드에 run이 여럿이면 `--run K`가 필수다.
- `--router-backend NAME`(레지스트리 이름, 예 `jev`)과 `--router-fallback NAME`(백엔드를 줄 때 기본 `subscription`, `none` 가능): router 실행에만 eval workdir 복사본의 `.model-effort-router.json`에 `difficulty.backend/fallback`을 병합해 쓴다(fixture의 gate 설정은 유지, fixture 자체는 수정하지 않는다). **`jev`는 작업 텍스트를 TypeSafe(외부 API, 구독과 별도 과금)로 보낸다.** live 배너가 이를 알린다. `TYPESAFE_API_KEY`는 환경에 있어야 하며 이 도구는 값을 읽지 않는다.
- router 기록의 `classifier_backend`(실제로 판정한 backend), `classifier_fallback`, `classifier_fallback_causes`(예 `jev:TimeoutError`)로 폴백 여부와 원인을 확인한다. Jev의 사용량은 `{input_tokens, output_tokens}`로 오며 cached 필드 없이 그대로 합산된다.

## 독립 라벨링 (labeling-guide §4)

라벨은 코퍼스와 따로 둔 파일에 단다. 라벨러는 서로의 파일과 `proposed`를 보지 않는다.

- 빈 시트: `python3 -m evaluation.labels sheet evaluation/corpus/seed.jsonl OUT.tsv` (id, task, paths만 담김).
- 시트 열: `level`은 L1~L5(no_route면 비움), `risk_flags`는 쉼표 구분, `target`은 route / plan_only / review_only / no_route.
- 합치기: `python3 -m evaluation.labels merge evaluation/corpus/seed.jsonl OUT.jsonl evaluation/corpus/labels-claude.jsonl evaluation/corpus/labels-user.tsv`. 라벨 2개가 모인 케이스는 `labeled`가 되고 `proposed`는 빠진다. 일치 보고(discuss / revise_guide)를 출력한다.
- 시드 40건: `labels-claude.jsonl`(메인 세션), `labels-opus.jsonl`(라벨을 보지 않은 별도 Opus 에이전트), 합의 결과 `seed-labeled.jsonl`(40건 adjudicated, 35건 일치, 2026-10-01). 사람 라벨러는 아직 없다.
- 확장 110건: `expansion.jsonl`(초안), `labels-exp-opus.jsonl`·`labels-exp-sonnet.jsonl`(독립 라벨), `expansion-labeled.jsonl`(100건 일치, 10건 합의). 시드와 합친 150건: `corpus-v1.jsonl`(L1 26, L2 32, L3 34, L4 23, L5 15, no_route 20; 위험 신호 47건; plan_only 11, review_only 10). 라벨러는 모두 AI 에이전트이고 사람 라벨은 아직 없다.
- **v2 합본 300건:** `evaluation/corpus/corpus-v2.jsonl`. 기존 v1 150건을 보존하고 새 `add-001`~`add-150`을 추가했다. L1 51, L2 49, L3 50, L4 50, L5 50, no_route 50; 난이도 평가 250건, target 평가 300건. route 189, plan_only 31, review_only 30, no_route 50; 위험 신호 사례 104건(34.7%).
- v2 추가분 provenance (2026-10-04): `expansion-v2.jsonl`은 작성자의 `proposed`를 가진 draft, `labels-v2-a.jsonl`·`labels-v2-b.jsonl`은 서로 다른 Codex 에이전트의 독립 라벨이다. 라벨러에게는 id/task/paths/status만 제공하고 proposed·note·서로의 라벨·backend 예측을 숨겼다. 139/150건 완전 일치(92.7%), 나머지 11건은 가이드에 따라 두 라벨러와 메인 세션이 합의했고 이유를 `expansion-v2-labeled.jsonl`의 note에 기록했다. 2단계 이상 난이도 차이는 없었다. AI 라벨이며 사람의 독립 검증은 아직 없다.
- v2는 레벨 균형을 목표로 만든 합성 표본이며 실제 사용자 요청 빈도를 나타내지 않는다. 기존 v1은 질문·임계값 조정에 사용됐으므로 300건 전체를 독립 holdout으로 부르지 않는다. 새 150건의 결과와 합본 결과를 따로 보고해야 한다. v1의 기존 live 점수는 v2 점수가 아니다. 확장 후 1,200회 새 live 호출을 수행한 결과는 [v2 live 비교](live-router-comparison-v2-20261004.md)에 있다(기존/보강 질문 × Jev/Nimble; 네 조건 모두 fallback 0).

v2 합본 검증 및 비교 준비(모델 호출 없음):

```sh
python3 -m evaluation.cases evaluation/corpus/corpus-v2.jsonl
python3 -m evaluation.compare --corpus evaluation/corpus/corpus-v2.jsonl --backends jev,nimble --dry-run
```

- 2026-10-01부터 `compare`는 no_route 케이스도 분류기를 돌려 target을 채점한다. 그래서 `tokens`, 지연, `fallback_count`에 no_route 케이스가 포함되며 이전 보고서와 직접 비교할 수 없다.
- 파일럿 세트 v2 (`evaluation/pilot/cases-v2.jsonl`, 13건, 같은 fixture): 기존 4건 + 9건. L1 2, L2 4, L3 4, L4 2, L5 1. 위험 신호 6건(auth, data_loss, payment, data_migration, concurrency, security+auth). 작성자 단일 라벨(`pilot`).

## Claude Code host (`--host claude`)

`live_runner --host claude` compares `mer --host claude` with stock Claude Code: the baseline is `claude -p --output-format json --permission-mode auto [--model M] [--effort E] -- PROMPT` (no `--model` = Claude Code's default; the Agent tool stays allowed). No rollouts are read (`~/.codex/sessions` is untouched): usage comes from the `claude -p` results (baseline) or mer's `calls[].usage` (router). Records carry `host` and `cost_usd`: the baseline's `total_cost_usd`, or for the router the sum over sessions of the LAST reported `total_cost_usd` of each session (it is cumulative per session, and includes a small side call that `usage` omits); `None` if any call or the run lacks it (an errored run, a timed-out resume, a thread-less call). `model_usage` (per-model input/cached/cache-write/output from the last `modelUsage` per session, same None rule) is the fuller token count since `usage` likely omits Agent-subagent tokens; `evaluation.cost` takes tokens from it when present. Classifier spend (Jev or the Haiku classifier) is not in `cost_usd`; its tokens are reported separately, as for Codex. Both modes load the user's global Claude settings and plugins and every CLAUDE.md up the workdir's parent chain, so absolute numbers carry that overhead while the A/B stays fair. `evaluation.cost` uses that `cost_usd` for claude records (`claude:no_cost` when unreported) and rollouts for codex records.

Lean context (`session.claude_context`, default `lean`): mer's claude implement/resume sessions load all settings and instructions (CLAUDE.md, `~/.claude/rules`, user permissions and hooks) but turn the enabled plugins off (`--settings` `enabledPlugins: false`, read from the user and workdir settings) and MCP servers off. Lean read-only (review/plan) sessions load only user settings with all hooks disabled. `claude_context: full` keeps everything. The stock Claude baseline always runs full, so a lean router run is cheaper in fixed context by design; record which context a pilot used.

## L2 경계 단독 실험과 조건부 Jev 재판정 (2026-10-04)

[600회 live 실험과 혼합 재생 보고서](l2-boundary-experiment-20261004.md). 새 L2 질문은 Nimble에서 회귀하여 기각했다. 이전 보강 질문 + 위험/불확실/계획·리뷰 요청의 Jev 재판정은 재생에서 94.8%, Jev 호출 56.0%였다. 제품에는 적용하지 않았다. [실제 연쇄 호출 검증](conditional-chain-live-20261005.md)은 완료됐으며 독립 holdout 검증은 남아 있다. [40건 사람 검토 시트](../../evaluation/corpus/human-review-v2-boundaries.tsv)는 기존 라벨·예측을 숨긴 빈 시트이며 아직 사람 검토 전이다.

## 경계 라벨 40건 검토 (2026-10-05)

[독립 AI 검토와 점수 민감도](boundary-label-review-20261005.md): 두 검토자 39/40 일치, 기존 라벨에 레벨 6건·위험 플래그 3건의 공통 이견이 있었다. 공식 정답과 빈 사람 검토 시트는 보존했다. L2 점수는 라벨 경계에 민감하지만 새 L2 질문 기각은 민감도 계산에서도 유지된다.

## L2 구현·리뷰 의도와 코드/diff 진단 (2026-10-05)

[192회 paired live 진단](intent-context-ablation-20261005.md): 새로운 합성 예제 12개를 두 의도·두 정보 조건·두 반복으로 비교했다. Nimble L2는 구현 75.0%/62.5%, 리뷰 25.0%/0.0%; Jev는 모두 100%. 코드/diff만 더 주어서는 리뷰 하락이 해결되지 않았고, 콜백 예제 1개에서 별도 후처리 승격 오류가 있었다. AI 정답의 소규모 진단이며 제품과 기존 300건 코퍼스는 보존했다.

## 조건부 Jev 실제 연쇄 호출 (2026-10-05)

[551회 live 호출 검증](conditional-chain-live-20261005.md): Nimble 348회 후 조건에 맞는 203건만 같은 입력으로 Jev를 이어 호출했다. 기존 300건의 난이도 정확도 95.2%, critical miss 1건, Jev API 호출 44.0% 절감으로 사전 기준을 통과했다. 진단 리뷰 L2는 두 조건 모두 8/8로 회복했고 구현+코드에는 미선택 오답 1건이 남았다. 실측 코퍼스 연쇄 p50/p95는 1,165.5/1,415.8ms다. 제품과 코퍼스는 유지했으며 사람 라벨·실제 요청 holdout·live 장애 검증은 남아 있다.

## 합성 진단 300건 추가: v3 (2026-10-05)

사용자 승인에 따라 실제 요청 holdout과 구분한 **합성 진단**을 추가했다. 현재 합본은 [corpus-v3.jsonl](../../evaluation/corpus/corpus-v3.jsonl) 600건이다. v2 300건은 바이트 그대로 앞부분에 보존했다. 새 300건은 [expansion-v3-labeled.jsonl](../../evaluation/corpus/expansion-v3-labeled.jsonl)로 별도 평가한다. 기존 live 점수는 v3 점수가 아니다.

| 최종 라벨 | 추가 300건 | 합본 600건 |
| --- | ---: | ---: |
| L1 | 30 | 81 |
| L2 | 150 | 199 |
| L3 | 30 | 80 |
| L4 | 30 | 80 |
| L5 | 30 | 80 |
| no_route | 30 | 80 |

추가 L2는 구현 60·리뷰 60·계획 30건이다. L2를 집중 진단하기 위해 추가분의 50%로 구성했으며, 합본에서는 199/600(33.2%)이다. 추가분 target은 route 119, review_only 92, plan_only 59, no_route 30; 위험 신호 사례 109건(36.3%)이며 6종 모두 포함한다. 백엔드/데이터, 클라이언트/모바일, 도구/인프라 영역과 한국어·영어 요청을 포함한다.

초안 [expansion-v3.jsonl](../../evaluation/corpus/expansion-v3.jsonl)의 proposed는 정답이 아니다. 두 별도 AI 에이전트에 id/task/paths와 고정 가이드만 전달하고 작성자 제안·메모·상대 라벨·백엔드 예측을 숨겼다. 독립 판정은 [labels-v3-a.jsonl](../../evaluation/corpus/labels-v3-a.jsonl), [labels-v3-b.jsonl](../../evaluation/corpus/labels-v3-b.jsonl)에 보존한다. 난이도와 target은 300/300 일치, 위험 플래그를 포함한 완전 일치는 290/300(96.7%)였다. 플래그 차이 10건은 두 라벨러가 기존 가이드로 논의해 합의했고 사유를 최종 파일 note에 남겼다. 2단계 이상 차이는 없었으며 가이드는 변경하지 않았다. 의미가 겹친 작업은 별도 품질 검토 후 교체하고 다시 독립 라벨링했다. 정규화한 요청 문장의 정확 중복은 기존분·추가분 사이에 없다.

AI 라벨이며 사람 검증은 아직 없다. 실제 사용자 빈도를 나타내거나 실제 요청 holdout을 대체하지 않는다. 제품·설정·기존 코퍼스는 변경하지 않았고 새 live 분류 호출은 0회다. 두 파일의 스키마 검증과 아래 dry-run을 통과했다(난이도 평가 대상 추가 270건, 합본 520건; target은 전부 평가).

```sh
python3 -m evaluation.cases evaluation/corpus/expansion-v3-labeled.jsonl
python3 -m evaluation.cases evaluation/corpus/corpus-v3.jsonl
python3 -m evaluation.compare --corpus evaluation/corpus/expansion-v3-labeled.jsonl --backends jev,nimble --dry-run
python3 -m evaluation.compare --corpus evaluation/corpus/corpus-v3.jsonl --backends jev,nimble --dry-run
```

## v3 600건 live 평가 (2026-10-05)

[2,400회 새 live 성능 평가](live-router-comparison-v3-20261005.md)를 완료했다(기존/보강 질문 × Jev/Nimble). 전송 오류·fallback은 0건이다. 새 표본의 난이도 정확도는 Jev 97.4%/96.3%, Nimble 78.5%/76.7%; 새 L2 리뷰 60건의 Nimble 정확도는 56.7%/23.3%다. 두 backend 모두 보강 질문의 합본 점수는 올랐지만 새 표본 전체 점수는 낮아졌다. 합성 AI 라벨 평가이며 제품·질문·임계값·코퍼스는 보존했다.

## v3 개선 후보 검증 (2026-10-05)

[696회 새 live 개선 후보 검증](improvement-validation-v3-20261005.md)을 완료했다. 고정 조건부 Jev는 같은 실행의 Nimble 207/270에서 260/270(96.3%)으로 개선됐고 L2 리뷰는 60/60이었다. Jev 추가 호출은 212/300(70.7%)이므로 비용·속도 우위는 입증하지 않았다. 구현 접두어 후보는 새 원문 쌍 비교에서 L2 리뷰 33/60→29/60으로 하락해 탈락했다. 호출 오류는 없고 제품·설정·코퍼스는 보존했다. 이미 평가한 합성 표본의 후보 검증이며 실제 요청 holdout을 대체하지 않는다.

## 실제 요청 평가 준비 (2026-10-05)

[Codex 대화 수집·사람 검수 준비](real-holdout-preparation-20261005.md)를 진행했다. 고유 후보 132개에서 독립 입력 후보 25개를 선별하고 빈 검수 시트를 만들었다. 나머지는 선행 맥락 필요 83개, 자동 주입·보고문 24개다. 목표 100~200개에는 미달하며 라우터 프로젝트에 편중됐다. 사용자가 25개를 직접 검수하기로 했으며 현재 사람 정답 0개·새 분류 호출 0회로 실제 요청 성능 비교는 미실행이다.

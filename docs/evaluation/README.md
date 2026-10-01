# 평가 도구 사용법

모든 도구는 저장소 루트에서 Python 3 표준 라이브러리만으로 실행한다. 평가 코드는 `evaluation/`(플러그인 번들에 포함되지 않음)에 있다.

**중요: 모델을 호출하는 경로는 전부 `--live`가 있어야 실행된다. live 실행은 구독 사용량을 소모하므로 사용자의 명시적 결정이 있을 때만 실행한다. 테스트와 dry-run은 모델을 호출하지 않는다.**

| 도구 | 기본(모델 호출 없음) | `--live` |
|---|---|---|
| 코퍼스 검증과 라벨러 일치율 | `python3 -m evaluation.cases evaluation/corpus/seed.jsonl` | 해당 없음 |
| Backend 비교 | `python3 -m evaluation.compare --corpus C.jsonl --backends NAME --dry-run` (fake/등록된 오프라인 Backend는 `--live` 없이 실행) | `subscription` Backend는 `--live` 필요. 케이스당 `codex exec` 1회(입력 약 29.8k 토큰) |
| 비용 기준선 실행 | `python3 -m evaluation.live_runner --cases C.jsonl --fixture DIR --out runs.jsonl` (실행 계획만 출력) | `--live`를 붙이면 케이스마다 baseline과 router 두 번 `codex exec` 실행 |
| 기준선 비교 보고 | `python3 -m evaluation.baseline report runs.jsonl --md out.md --json out.json` | 해당 없음 (기록 파일만 읽음) |
| 요구사항 충족 기록 | `python3 -m evaluation.baseline mark runs.jsonl CASE_ID baseline\|router yes\|no [--run K]` | 해당 없음 (수동 판단) |

## 순서

1. `docs/evaluation/labeling-guide.md`대로 `seed.jsonl`의 draft를 독립 라벨링하고 새 코퍼스 파일(`evaluation/corpus/*.jsonl`)에 `labeled` → `adjudicated`로 옮긴다. `seed.jsonl`의 `proposed`는 정답이 아니다.
2. `evaluation.cases`로 일치 확인. `discuss`는 합의, `revise_guide`는 가이드 보완 후 재라벨.
3. `evaluation.compare`로 Backend 비교(exact, ±1, over/under, critical miss, latency, 토큰, fallback, 단계 프로필 일치).
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

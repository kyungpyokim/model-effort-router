# 평가 도구 사용법

모든 도구는 저장소 루트에서 Python 3 표준 라이브러리만으로 실행한다. 평가 코드는 `evaluation/`(플러그인 번들에 포함되지 않음)에 있다.

**중요: 모델을 호출하는 경로는 전부 `--live`가 있어야 실행된다. live 실행은 구독 사용량을 소모하므로 사용자의 명시적 결정이 있을 때만 실행한다. 테스트와 dry-run은 모델을 호출하지 않는다.**

| 도구 | 기본(모델 호출 없음) | `--live` |
|---|---|---|
| 코퍼스 검증과 라벨러 일치율 | `python3 -m evaluation.cases evaluation/corpus/seed.jsonl` | 해당 없음 |
| Backend 비교 | `python3 -m evaluation.compare --corpus C.jsonl --backends NAME --dry-run` (fake/등록된 오프라인 Backend는 `--live` 없이 실행) | `subscription` Backend는 `--live` 필요. 케이스당 `codex exec` 1회(입력 약 29.8k 토큰) |
| 비용 기준선 실행 | `python3 -m evaluation.live_runner --cases C.jsonl --fixture DIR --out runs.jsonl` (실행 계획만 출력) | `--live`를 붙이면 케이스마다 baseline과 router 두 번 `codex exec` 실행 |
| 기준선 비교 보고 | `python3 -m evaluation.baseline report runs.jsonl --md out.md --json out.json` | 해당 없음 (기록 파일만 읽음) |
| 요구사항 충족 기록 | `python3 -m evaluation.baseline mark runs.jsonl CASE_ID baseline\|router yes\|no` | 해당 없음 (수동 판단) |

## 순서

1. `docs/evaluation/labeling-guide.md`대로 `seed.jsonl`의 draft를 독립 라벨링하고 새 코퍼스 파일(`evaluation/corpus/*.jsonl`)에 `labeled` → `adjudicated`로 옮긴다. `seed.jsonl`의 `proposed`는 정답이 아니다.
2. `evaluation.cases`로 일치 확인. `discuss`는 합의, `revise_guide`는 가이드 보완 후 재라벨.
3. `evaluation.compare`로 Backend 비교(exact, ±1, over/under, critical miss, latency, 토큰, fallback, 단계 프로필 일치).
4. 비용 기준선: fixture 저장소(router 모드용은 플러그인 hooks 설정을 `.codex/`에 포함)를 준비하고 `live_runner`로 실행. 실행마다 fixture의 임시 복사본을 만들고 끝나면 지운다. 끝난 뒤 `mark`로 요구사항 충족 여부를 사람이 기록하고 `baseline report`로 판정한다.

## 판정 규칙 (§22.3)

Router가 품질을 유지하면서 전체 사용량(메인 세션 + 분류 호출 + 모든 subagent)을 줄이지 못하면 기본 모드를 `auto`로 두지 않는다. 보고서의 `decision.verdict`는 `auto_allowed`, `do_not_default_to_auto`, `insufficient_data`(짝이 없거나 `requirements_met` 미기록) 중 하나다.

## live_runner 사전 조건 (직접 해야 함)

- **플러그인 설치와 hook 신뢰는 사용자가 live 실행 전에 직접 한다.** 신뢰되지 않은 hook은 Codex가 건너뛰므로 "router" 실행이 조용히 두 번째 baseline이 된다. 이 도구는 hook 신뢰를 우회하지 않는다(`--dangerously-bypass-hook-trust` 미사용). router 기록은 route log에 `route`와 `stage_spawn` 이벤트가 있을 때만 `router_active: true`이고, 아니면 보고서에서 제외된다.
- 플러그인이 전역 설치되어 있으면 baseline 실행도 라우팅될 수 있다. baseline에서 router 활동(route 이벤트 또는 `mer_` subagent rollout)이 보이면 `contaminated: true`로 기록되고 보고서에서 제외된다.
- 실행은 **고정된 eval workdir 하나**(`--workdir`, 기본 `<state dir>/eval-workdir`, realpath)를 매번 지우고 fixture로 다시 채워 쓴다. Codex가 이 경로에 대해 `~/.codex/config.toml`에 `trust_level` 항목을 **하나 영구 저장**한다. 끝나면 직접 지워도 된다. 도구는 workdir이 없거나 자신이 만든 마커 파일(`.mer-eval-workdir`)이 있을 때만 내용을 지운다. 마커 없는 기존 디렉터리, fixture와 같거나 그 안팎인 경로, 현재 디렉터리·홈·루트(또는 그 상위)는 아무것도 지우지 않고 거부한다(종료 코드 1).
- 케이스 하나가 실패하면 `error`가 있는 기록(gate `incomplete`)을 남기고 다음 케이스로 계속한다. 이런 기록이 있으면 판정은 `insufficient_data`다.
- Review 결과는 오케스트레이터가 마지막에 `mer-gate --session <id> --review approved|changes_requested --findings N`으로 남긴다(주입 지시문에 포함). 기록의 `review_findings`와 보고서에 반영된다.

## 알려진 한계

- subagent 사용량은 rollout 파일의 `token_count` 이벤트에서 읽는다. 이 이벤트의 JSON 형태는 Codex 0.159.2 실제 rollout으로 확인했고 `evaluation/usage.py`의 `_token_count_total` 한 함수에 격리했다. rollout에 token_count가 없으면 0으로 치지 않고 `stages_without_usage`로 보고하며 판정은 `insufficient_data`가 된다. router 실행에서 subagent rollout이 하나도 없어도 마찬가지다.
- 분류 호출 사용량은 Backend가 보고한 실측값이다(`classifier_usage`를 route 이벤트에 기록, 호출이 실패한 경우 포함). 모델을 호출하는 Backend가 실행됐는데 사용량을 보고하지 않으면 route 이벤트에 `classifier_usage: null`을 명시하고(키 없음 = 모델 호출 없음 = 0), null이 있으면 추정하지 않고 실행을 `classifier_usage_missing`(불완전)로 표시한다. 종료 코드가 0이 아닌 호출의 사용량은 얻을 수 없다.
- rollout은 실행 시작 이후에 수정된 파일 중 첫 줄의 `session_id`가 일치하는 것만 읽는다.
- 전체 사용량은 `input + output` 토큰 합이다. 모델별 가중 비용은 계산하지 않는다.
- TODO(Phase 6): confidence 보정, cost와 로컬 자원 사용량 비교.

## Pilot (Baseline vs Router, 4 cases)

fixture `evaluation/pilot/fixture/`(작은 Python 상점 서비스, gate는 `python3 -m unittest`)와 `evaluation/pilot/cases.jsonl`(L1~L4, L4는 `auth`). 라벨은 파일럿 작성자가 정한 값이며 코퍼스 정답이 아니다. fixture는 git 저장소가 아니어도 된다(`--skip-git-repo-check`).

설정: baseline = `gpt-6-luna` / `high`, router 메인 세션 = `gpt-6-luna` / `low`(단계 subagent는 Router가 선택). 기록의 `model`/`effort`에 실행별 값이 남는다. 먼저 플러그인 설치와 hook 신뢰를 직접 끝낸다.

사용자 승인 후 실행할 live 명령(구독 사용량 소모, codex exec 8회):

```
python3 -m evaluation.live_runner --cases evaluation/pilot/cases.jsonl --fixture evaluation/pilot/fixture --out pilot-runs.jsonl --baseline-model gpt-6-luna --baseline-effort high --router-model gpt-6-luna --router-effort low --live
```

실행 후:
1. 케이스·모드별로 결과를 직접 확인하고 `python3 -m evaluation.baseline mark pilot-runs.jsonl CASE_ID baseline|router yes|no` (pilot-l1, pilot-l2, pilot-l3, pilot-l4-auth 각각 두 모드).
2. `python3 -m evaluation.baseline report pilot-runs.jsonl --md pilot.md --json pilot.json`

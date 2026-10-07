# 평가 도구

현재 분류 계약인 `role`과 `effort`를 평가한다. 과거 L1–L5 코퍼스와 보고서는 보존된 역사 자료이며 현재 라벨러 도구에서 읽거나 새 점수에 섞지 않는다. 두 형식은 의미가 달라 자동 변환하지 않는다.

## 흐름

1. [`labeling-guide.md`](labeling-guide.md)에 따라 두 명 이상이 같은 요청과 경로를 보고 독립적으로 role/effort를 고른다.
2. 빈 라벨 시트를 만들고 각 라벨러가 별도 파일에 입력한다.

   ```sh
   python3 -m evaluation.labels sheet evaluation/corpus/role-effort-seed.jsonl labels-a.tsv
   python3 -m evaluation.labels sheet evaluation/corpus/role-effort-seed.jsonl labels-b.tsv
   ```

3. 라벨을 합쳐 일치율과 불일치 ID를 확인한다.

   ```sh
   python3 -m evaluation.labels merge evaluation/corpus/role-effort-seed.jsonl labeled.jsonl labels-a.tsv labels-b.tsv
   python3 -m evaluation.cases labeled.jsonl
   ```

4. 합의한 role/effort를 각 `final`에 기록하고 상태를 `adjudicated`로 바꾼다. 분류 점수는 [`evaluation.compare`](../../evaluation/compare.py)의 Python API가 adjudicated 케이스에 대해 role 정확도, effort 정확도, 동시 정확도를 계산한다.

첫 40건은 `evaluation/corpus/role-effort-v1.jsonl`에 수록되어 있다. 두 AI 라벨러의 독립 라벨 일치율은 role 38/40, effort 33/40, 동시 31/40이며, 불일치는 경계 기준을 보완한 뒤 판정했다. [Jev/Nimble 첫 비교 결과](role-effort-comparison-20261006.md)를 확인할 수 있다. 이 합성 시드는 실제 사용자 요청 분포를 대표하지 않으며 사람의 독립 검증도 거치지 않았다.

확장 개발 세트 160건과 분리 holdout 40건은 각각 `role-effort-dev-v2.jsonl`, `role-effort-holdout-v1.jsonl`에 있다. 과거 `corpus-v3.jsonl`에서 task/path만 가져와 기존 role/effort 라벨을 제거한 후 두 라벨러가 독립 라벨링했다. 두 라벨 모두 AI 판정이며 불일치가 많아 아직 `labeled` 상태다. Jev/Nimble 잠정 점수는 각 라벨러를 별도 기준으로 계산했고 사람 판정 정확도로 해석하면 안 된다. [확장 결과와 검토 시트](role-effort-expansion-20261006.md)를 확인한다.

사람 판정 holdout 초안 250건은 `role-effort-human-holdout-v2.jsonl`에 있다. `corpus-v3.jsonl`의 600건 중 dev-v2 및 기존 holdout-v1과 task/path가 겹치는 200건을 제외한 나머지 400건에서 seed `20261006`으로 뽑았다. 원본의 legacy/AI 라벨은 복사하지 않았다. `role-effort-human-holdout-v2-a.tsv`와 `role-effort-human-holdout-v2-b.tsv`를 서로 독립된 두 명이 채우고, 각자 상대의 시트·모델 출력·옛 라벨을 보지 않도록 한다. 두 시트가 완료되면 다음 명령으로 합의 상태를 확인한다.

```sh
python3 -m evaluation.labels merge \
  evaluation/corpus/role-effort-human-holdout-v2.jsonl \
  evaluation/corpus/role-effort-human-holdout-v2-labeled.jsonl \
  evaluation/corpus/role-effort-human-holdout-v2-a.tsv \
  evaluation/corpus/role-effort-human-holdout-v2-b.tsv
```

불일치는 `labeling-guide.md`에 따라 사람끼리 판정하고 `final`을 기록한 뒤에만 최종 정확도를 계산한다. 250건은 정확도가 약 80%일 때 이항 근사 오차폭이 대략 ±5%p인 크기다. 다만 이 표본도 합성 코퍼스에서 나왔으므로 실제 사용자 요청에 대한 검증을 대신하지 않는다.

두 사람의 첫 라벨 간 일치는 role 245/250 (98.0%), effort 198/250 (79.2%), 동시 194/250 (77.6%)였다. 불일치 56건(역할만 4, effort만 51, 두 차원 모두 1)은 [판정 시트](../../evaluation/corpus/role-effort-human-holdout-v2-adjudication.tsv)에서 합의해 최종 라벨로 확정했다. 최종 결과는 `role-effort-human-holdout-v2-adjudicated.jsonl`에 있다.

250건을 모두 사람 판정한 뒤 조정된 프롬프트를 한 번 측정했다. Jev (`jev-latest`)는 role 214/250 (85.6%, 95% Wilson CI 80.7–89.4), effort 174/250 (69.6%, 63.6–75.0), joint 143/250 (57.2%, 51.0–63.2)였다. Nimble은 role 181/250 (72.4%, 66.6–77.6), effort 154/250 (61.6%, 55.4–67.4), joint 103/250 (41.2%, 35.3–47.4)였다. 두 backend 모두 실패 없이 250건을 처리했다. 앞서 정한 초기 기준(role 85%, effort 80%, joint 75%)에서 Jev는 role만 통과했다. xhigh 재현율은 Jev 12/26 (46.2%), Nimble 7/26 (26.9%)로 특히 낮고 표본도 작다. 이 holdout은 prompt 조정에 재사용하지 않는다. 측정 원본은 `runs/role-effort-human-holdout-v2-comparison-20261006.json`에 있다.

2026-10-06에 이 holdout의 role 오류 사례와 effort 혼동 방향을 보고 role 기준 문장을 추가했다. 따라서 holdout v2는 더 이상 깨끗한 최종 평가셋이 아니며, 이후에는 **사람 판정 조정용 세트**로 쓴다. AI 라벨인 dev-v2는 effort 오류 방향이 사람 판정과 반대로 나타나므로(dev에서는 Jev가 낮게, 사람 판정에서는 높게 예측) effort 조정 근거로 쓰지 않는다.

새 최종 평가셋은 `role-effort-human-holdout-v3.jsonl` 150건이다. `corpus-v3.jsonl` 600건 중 dev-v2, holdout-v1, holdout-v2, seed, v1과 task/path가 겹치지 않는 나머지 전부이며, 순서는 seed `20261007`로 섞었다. 겹치는 task 문장이나 유사도 0.8 이상의 근사 중복은 없다. task/path만 복사했고 legacy 라벨은 넣지 않았다. 150건은 정확도 약 80%에서 이항 근사 오차폭이 대략 ±6.4%p다. `role-effort-human-holdout-v3-a.tsv`부터 `-e.tsv`까지 다섯 판정 시트를 사용했다. a 시트의 role/effort/note는 사용자 요청으로 Codex가 채웠다. 나머지 시트의 작성 주체와 독립성은 이 실행 기록만으로 확인할 수 없으므로 사람 5명의 독립 판정 정확도로 해석하지 않는다. 판정과 최종 측정이 끝나기 전에는 이 세트로 프롬프트를 조정하거나 오류 사례를 열람하지 않는다.

```sh
python3 -m evaluation.labels merge \
  evaluation/corpus/role-effort-human-holdout-v3.jsonl \
  evaluation/corpus/role-effort-human-holdout-v3-labeled.jsonl \
  evaluation/corpus/role-effort-human-holdout-v3-a.tsv \
  evaluation/corpus/role-effort-human-holdout-v3-b.tsv \
  evaluation/corpus/role-effort-human-holdout-v3-c.tsv \
  evaluation/corpus/role-effort-human-holdout-v3-d.tsv \
  evaluation/corpus/role-effort-human-holdout-v3-e.tsv
```

처음 두 시트(a, b)의 일치는 role 140/150, effort 89/150에 그쳐 세 시트(c, d, e)를 추가했다. 다섯 시트 모두 일치한 경우는 role 137건, effort 69건이다. effort에서 annotator-a는 다른 네 명보다 일관되게 한 단계 높게 판정했다(다른 판정자와 쌍별 effort 일치 84–100/150, 나머지 네 명끼리는 116–135/150). 차원별 다수결을 최종 라벨로 사용했다. 150건 모두 동률 없이 과반이 있었고, 3/5 다수결은 effort 25건, role 3건이다. 결과는 `role-effort-human-holdout-v3-adjudicated.jsonl`에 있다.

v3 공식 측정(커밋 `532e9e4`의 프롬프트, backend별 150회, 실패 0)은 다음과 같다. 초기 기준은 role 85%, effort 80%, joint 75%다.

| Backend | Role | Effort | Joint |
|---|---:|---:|---:|
| Jev (`jev-latest`) | 141/150 (94.0%, 95% Wilson CI 89.0–96.8) | 119/150 (79.3%, 72.2–85.0) | 111/150 (74.0%, 66.4–80.4) |
| Nimble | 124/150 (82.7%, 75.8–87.9) | 101/150 (67.3%, 59.5–74.3) | 85/150 (56.7%, 48.7–64.3) |

Jev는 role 기준을 넘었고 effort와 joint는 각각 1건, 2건 모자라지만 신뢰구간이 기준을 포함한다. Jev가 Nimble보다 role, effort, joint 모두 높다(McNemar exact p 0.00049, 0.0064, 0.00031). Jev의 남은 effort 약점은 실제 `medium`이다(12/24, `low`로 11건). 각 시트를 나머지 네 시트의 다수결과 비교한 effort 일치는 97–145/150이며(동률 시 최다 라벨 중 하나면 일치로 계산해 판정 시트 쪽에 유리함), Jev의 119는 그 범위 안에 있다. 측정 원본은 `runs/role-effort-human-holdout-v3-final-20261006.json`이다. 이 결과를 본 뒤로 v3도 조정에 쓰면 오염되므로, 이후 프롬프트 변경은 새 holdout으로 검증한다.

같은 날 현재 체크아웃으로 v3를 재측정한 결과 Jev는 role 142/150, effort 119/150, joint 111/150이었다. Nimble은 124/150, 101/150, 85/150으로 같았고 양쪽 모두 실패 0건이었다. 이 재측정은 별도 표본이 아닌 같은 150건의 반복 실행이다. 원본은 `runs/role-effort-human-holdout-v3-rerun-current.json`에 있다.

2026-10-07에 같은 v3 코퍼스로 OpenAI Decisions API (`gpt-6-luna`)를 비교했다. 150회 모두 성공했으며 role 136/150 (90.7%), effort 119/150 (79.3%), joint 107/150 (71.3%)였다. 기존 holdout의 재사용이므로 독립 정확도가 아닌 다수결 라벨 일치율이다. [상세 결과와 원시 예측](openai-decisions-20261007.md).

분류 backend를 실제 호출하면 설정에 따라 외부 서비스 또는 `codex exec`를 사용하고 사용량이 발생할 수 있다. 비교 API를 직접 실행하기 전에 대상 backend와 요청 텍스트 전송 여부를 확인한다. 이 저장소는 live 비교를 자동 실행하지 않는다.

## 실행 정책 파일럿

현재 실행 정책의 탐색 결과는 [low 시작·승격 파일럿](low-first-escalation-pilot-20261006.md)에 기록했다. 같은 `gpt-6-luna`로 기존 13개 fixture 작업을 비교했으며 과거 L1–L5 라벨은 사용하지 않았다. 리뷰로 보완한 검사에서 low 첫 시도는 11/13, medium 승격 후는 13/13, high 1회는 11/13이었다. 승격까지 합친 worker 토큰은 22.0% 적었다. 결과를 본 뒤 검사기를 보완한 작은 탐색이므로 분류 정확도나 일반 작업 성공률로 해석하지 않는다.

## 과거 평가 자료

`evaluation/corpus/`의 기존 L1–L5 라벨, `evaluation/pilot/`, 날짜가 붙은 평가 보고서는 변경하지 않고 보존한다. 과거 실험 결과는 해당 시점의 방식으로만 해석한다. 새 라벨링은 `evaluation/corpus/role-effort-seed.jsonl`에서 시작하고 adjudicated 데이터는 `role-effort-v1.jsonl`에 저장한다.

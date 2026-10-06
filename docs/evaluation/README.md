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

분류 backend를 실제 호출하면 설정에 따라 외부 서비스 또는 `codex exec`를 사용하고 사용량이 발생할 수 있다. 비교 API를 직접 실행하기 전에 대상 backend와 요청 텍스트 전송 여부를 확인한다. 이 저장소는 live 비교를 자동 실행하지 않는다.

## 과거 평가 자료

`evaluation/corpus/`의 기존 L1–L5 라벨, `evaluation/pilot/`, 날짜가 붙은 평가 보고서는 변경하지 않고 보존한다. 과거 실험 결과는 해당 시점의 방식으로만 해석한다. 새 라벨링은 `evaluation/corpus/role-effort-seed.jsonl`에서 시작하고 adjudicated 데이터는 `role-effort-v1.jsonl`에 저장한다.

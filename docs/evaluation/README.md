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

분류 backend를 실제 호출하면 설정에 따라 외부 서비스 또는 `codex exec`를 사용하고 사용량이 발생할 수 있다. 비교 API를 직접 실행하기 전에 대상 backend와 요청 텍스트 전송 여부를 확인한다. 이 저장소는 live 비교를 자동 실행하지 않는다.

## 과거 평가 자료

`evaluation/corpus/`의 기존 L1–L5 라벨, `evaluation/pilot/`, 날짜가 붙은 평가 보고서는 변경하지 않고 보존한다. 과거 실험 결과는 해당 시점의 방식으로만 해석한다. 새 라벨링은 `evaluation/corpus/role-effort-seed.jsonl`에서 시작하고 adjudicated 데이터는 `role-effort-v1.jsonl`에 저장한다.

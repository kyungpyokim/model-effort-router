# Role / effort 라벨링 가이드

활성 평가 라벨은 요청에 필요한 **role**과 **effort**다. 허용 값은 런타임 계약인 `model_effort_router/difficulty/decision.py`의 `ROLES`와 `EFFORTS`가 정한다. 기존 L1~L5 코퍼스와 보고서는 역사 자료로 보존하며 새 스키마로 변환하거나 활성 평가에 섞지 않는다. 새로 라벨링할 케이스는 `evaluation/corpus/role-effort-seed.jsonl`에서 시작한다.

## 1. 스키마

케이스 한 건은 JSONL 한 줄이다. 초안은 id, task, paths, status만 가진다. 라벨과 제안은 초안 파일에 넣지 않는다.

```json
{"id":"seed-001","task":"Fix the null-pointer crash in parse_date()","paths":["date_utils.py"],"status":"draft"}
```

라벨은 독립 파일 또는 `labels.py sheet`로 작성한다. 코퍼스 안의 `labels` 항목에는 `labeler`도 기록한다. 판정이 끝난 케이스는 두 명 이상의 라벨과 `final`을 갖는다.

```json
{"id":"seed-001","task":"Fix the null-pointer crash in parse_date()","paths":["date_utils.py"],"status":"adjudicated",
 "labels":[{"labeler":"kim","role":"fix","effort":"low"},{"labeler":"lee","role":"fix","effort":"medium"}],
 "final":{"role":"fix","effort":"medium"}}
```

- `role`: `implementation`, `fix`, `lint`, `test`, `plan`, `design`, `review`, `analysis` 중 요청의 주된 작업 유형.
- `effort`: `low`, `medium`, `high`, `xhigh` 중 요청을 처리하는 데 필요한 추론 강도. 위험 표식이나 과거 난이도 등급이 아니다.
- `status`: `draft`(라벨 없음) → `labeled`(서로 독립된 라벨 2개 이상) → `adjudicated`(불일치 합의 후 `final`).
- `paths`는 선택 입력이다. 요청과 함께 경로를 제공하면 모든 라벨러에게 같은 경로를 보여준다.

모든 역할과 effort 값은 `evaluation/cases.py`가 런타임 상수에 따라 검증한다. 예전 `level`, `risk_flags`, `target` 필드는 허용하지 않는다.

## 2. 판단 기준

먼저 요청의 주된 작업을 role로 정하고, 별도로 필요한 추론 강도를 effort로 정한다. 두 라벨을 서로 추론해 정하지 않는다. 예를 들어 복잡한 결함 분석은 `fix`와 `high`일 수 있고, 단순한 구현 변경은 `implementation`과 `low`일 수 있다.

- `implementation`: 새 동작이나 기능 구현.
- `fix`: 기존 동작의 버그나 장애 수정.
- `lint`: 스타일, 정적 분석, 형식 문제 수정.
- `test`: 테스트 작성·수정·실행이 요청의 주된 목적.
- `plan`: 실행 전에 계획만 요청.
- `design`: 구조·인터페이스·기술 설계가 요청의 주된 결과물.
- `review`: 기존 변경이나 코드를 검토하고 수정하지 않음.
- `analysis`: 코드나 상황의 원인·동작 설명을 요청하며 구현하지 않음.

effort는 요청에 담긴 판단 난이도와 불확실성으로 고른다. 낮은 effort는 범위와 해법이 명확하고 국소적인 작업, medium은 보통 수준의 코드 이해나 몇 가지 선택이 필요한 작업, high는 여러 모듈의 상호작용·복수의 설계 선택·불확실한 원인 분석이 필요한 작업, xhigh는 광범위하고 결과 위험이 큰 문제를 깊게 추론해야 하는 작업에 쓴다. 파일 개수나 특정 단어만으로 자동 결정하지 않는다. 근거가 부족하면 과장하지 말고 보이는 요청 범위에서 가장 타당한 값을 고른다.

질문이나 설명 요청도 분석이 필요한 경우 `analysis`로 분류한다. 코드 관련 질문이라는 이유만으로 구현 role을 붙이지 않는다. 계획 요청은 `plan`, 검토만 요청은 `review`로 분류한다.

## 3. 독립 라벨링과 합의

1. 최소 두 명이 같은 `id`, `task`, `paths`만 보고 각자 라벨링한다. 서로의 라벨과 합의 기록은 가린다. 초안에는 제안 라벨이 없으므로 이를 숨기는 절차도 필요 없다.
2. `python3 -m evaluation.cases CORPUS.jsonl`로 합의를 확인한다. 보고서는 역할별 정확 일치, effort별 정확 일치, 두 차원의 **동시 일치**, 그리고 각 차원에서 불일치한 케이스 id를 출력한다. 세 명 이상일 때도 각 차원에서 모두 일치해야 정확 일치로 센다.
3. 불일치는 요청을 다시 읽고 각 라벨러가 독립적으로 근거를 설명한 뒤 합의한다. 불일치가 정의의 모호함에서 비롯됐다면 이 가이드에 기준을 보완하고, 필요하면 이전 라벨을 버린 뒤 보완된 기준으로 다시 독립 라벨링한다.
4. 합의된 `final`을 기록하고 상태를 `adjudicated`로 바꾼다. `evaluation/compare.py`는 이 활성 role/effort 라벨만 점수화한다.

시트와 병합 명령:

```sh
python3 -m evaluation.labels sheet evaluation/corpus/role-effort-seed.jsonl labels-a.tsv
python3 -m evaluation.labels merge evaluation/corpus/role-effort-seed.jsonl merged.jsonl labels-a.tsv labels-b.tsv
```

## 변경 이력

- 2026-10-06: 활성 판정 계약을 role/effort로 전환. 과거 L1~L5 라벨과 보고서는 그대로 보존하고, 새 초안 seed는 기존 seed에서 task/path만 가져온다.

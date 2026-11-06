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
- `effort`: `low`, `medium`, `high`, `xhigh`, `max` 중 요청을 처리하는 데 필요한 추론 강도. 위험 표식이나 과거 난이도 등급이 아니다.
- `tier`(선택): `economy`, `balanced`, `frontier` 중 하나(런타임 상수 `TIERS`). 라벨과 `final`에 role/effort 옆에 둘 수 있으며, 없으면 tier는 채점·합의 비교에서 제외된다. 기존 코퍼스는 tier 없이 그대로 쓴다.
- `status`: `draft`(라벨 없음) → `labeled`(서로 독립된 라벨 2개 이상) → `adjudicated`(불일치 합의 후 `final`).
- `context`(선택): hook이 보내는 세션 맥락("Session summary / Recent turns")을 재현할 때 쓴다. 라벨러는 현재 `task`만 분류하고 `context`는 해석에만 쓴다.
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

effort는 요청에 담긴 판단 난이도와 불확실성으로 고른다. low는 범위와 해법이 명확하고 넓은 맥락 없이 처리할 수 있는 국소 작업, medium은 관련 맥락을 읽거나 몇 가지 제한된 선택을 해야 하는 작업, high는 여러 부분의 상호작용·설계 tradeoff·불확실한 원인 분석이 필요한 작업, xhigh는 범위가 넓고 불확실성이 높으며 실수의 결과가 중대한 문제를 깊게 추론해야 할 때 쓴다. max는 여러 시스템에 걸친 가장 어렵고 불확실성이 큰 문제에 지속적인 깊은 추론이 꼭 필요한 경우에만 쓴다. 역할·파일 개수·특정 단어만으로 자동 결정하지 않는다. 관련 맥락 확인이 필요하면 최소 medium으로 본다.

질문이나 설명 요청도 분석이 필요한 경우 `analysis`로 분류한다. 코드 관련 질문이라는 이유만으로 구현 role을 붙이지 않는다. 계획 요청은 `plan`, 검토만 요청은 `review`로 분류한다.

## 3. 경계 기준

- 새 동작이나 기능을 추가해 달라는 요청은 `implementation`이다. 기존 동작의 결함을 고쳐 달라는 요청은 `fix`다. 설계 제안서나 아키텍처 결정을 결과물로 요청한 경우에만 `design`을 쓴다. 구현 문장 안의 “design” 같은 단어만으로 role을 정하지 않는다.
- 요청이 문서나 코드의 철자, 오타, 형식만 고치라고 하면 `lint`다.
- 결과가 명확한 단일 함수·컴포넌트의 국소 수정은 대체로 `low`다. 평범한 코드 이해나 작은 선택이 더해지면 `medium`, 여러 컴포넌트의 상호작용이나 불확실한 원인 분석은 `high`, 높은 불확실성과 중대한 결과 위험이 함께 있는 넓은 범위 작업은 `xhigh`를 고려한다.

## 3a. tier 판단 기준 (선택 라벨)

tier는 요청을 **처음 시도에 믿고 맡길 수 있는 모델 등급**이다. effort(얼마나 오래 생각해야 하나)와 따로 판단한다. effort를 올려도 모델이 모르는 API나 도메인 지식은 생기지 않는다는 점이 둘을 나누는 이유다.

- `economy`: 범위가 국소적이고(함수·클래스·모듈 하나, 지정된 버그 하나, 테스트, 단순 리팩터링), 범용 언어·표준 라이브러리·널리 쓰이는 프레임워크의 흔한 사용으로 풀리는 작업. 일반적인 웹·앱 UI의 레이아웃과 스타일(CSS, 흔한 UI 프레임워크)은 눈으로 확인해야 하더라도 economy다. 값·이름·오타를 지정해서 바꾸는 요청과 널리 알려진 개념의 설명은 아래 도메인에서도 economy다.
- `balanced`: 여러 모듈·계층을 잇는 기능, 비자명한 상태 관리, 아키텍처를 따라야 하는 변경. 아래 도메인 조건에는 해당하지 않는 일반 작업이다.
- `frontier`: 시스템 전반 아키텍처 설계, 여러 시스템에 걸친 미묘한 추론, 동시성·보안·데이터 손실처럼 실수가 치명적인 보장, 근본적인 설계 결정. **또는** 작업 크기와 상관없이 다음 중 하나가 정확성을 좌우하는 작업:
  - 버전에 따라 바뀌거나 학습 자료가 적은 좁은 도메인 API(DCC 도구 스크립팅, 게임 엔진, 그래픽 API, 셰이더 언어 등)를 정확히 써야 함
  - 좌표계·변환 행렬·회전 표현·투영·조명 같은 공간/기하/수치 추론이 필요함
  - 렌더링·그래픽 출력(3D 장면, 셰이더, 렌더링 파이프라인, 지오메트리)이라 테스트로 확인하기 어렵고 눈으로 봐야 틀린 걸 알 수 있음

도메인 단어("shader", "Blender", "render")만으로 올리지 않는다. Blender 프로젝트라도 범용 코드·파일만 건드리는 작업(패키징, 빌드·CI 스크립트, 파일 처리, 로그 파싱, 문서, 설정), 커밋·테스트 실행, 잘 알려진 기능 질문은 economy다. 세션 맥락이 Blender 작업이어도 현재 요청이 그런 작업이면 마찬가지다. 요청이 실제로 그 지식이나 추론을 요구하는지로 판단한다. 같은 Blender 요청이라도 상수 하나를 바꾸는 건 economy, bpy API로 노드 트리를 구성하는 건 frontier다.

## 4. 독립 라벨링과 합의

1. 최소 두 명이 같은 `id`, `task`, `paths`만 보고 각자 라벨링한다. 서로의 라벨과 합의 기록은 가린다. 초안에는 제안 라벨이 없으므로 이를 숨기는 절차도 필요 없다.
2. `python3 -m evaluation.cases CORPUS.jsonl`로 합의를 확인한다. 보고서는 역할별 정확 일치, effort별 정확 일치, 두 차원의 **동시 일치**, 그리고 각 차원에서 불일치한 케이스 id를 출력한다. 세 명 이상일 때도 각 차원에서 모두 일치해야 정확 일치로 센다.
3. 불일치는 요청을 다시 읽고 각 라벨러가 독립적으로 근거를 설명한 뒤 합의한다. 불일치가 정의의 모호함에서 비롯됐다면 이 가이드에 기준을 보완하고, 필요하면 이전 라벨을 버린 뒤 보완된 기준으로 다시 독립 라벨링한다.
4. 합의된 `final`을 기록하고 상태를 `adjudicated`로 바꾼다. `evaluation/compare.py`는 이 활성 role/effort 라벨과, 있으면 tier 라벨을 점수화한다.

시트와 병합 명령:

```sh
python3 -m evaluation.labels sheet evaluation/corpus/role-effort-seed.jsonl labels-a.tsv
python3 -m evaluation.labels merge evaluation/corpus/role-effort-seed.jsonl merged.jsonl labels-a.tsv labels-b.tsv
```

tier까지 라벨링할 때는 `sheet --tier`로 tier 열이 있는 시트를 만든다.

## 변경 이력

- 2026-10-06: 활성 판정 계약을 role/effort로 전환. 과거 L1~L5 라벨과 보고서는 그대로 보존하고, 새 초안 seed는 기존 seed에서 task/path만 가져온다.
- 2026-10-06: 첫 40건 role/effort 라벨링의 불일치를 판정하며 경계 기준을 구체화했다.
- 2026-11-05: 선택 라벨 `tier`와 판단 기준(3a)을 추가했다. 범위뿐 아니라 좁은 도메인 API 지식, 공간·기하 추론, 시각 결과의 검증 가능성을 본다.
- 2026-11-05: 리뷰 지적에 따라 3a를 보정했다. 일반 UI 레이아웃·스타일은 economy, 시각 결과 조건은 렌더링·그래픽 출력으로 한정, 도메인 조건과 겹치면 frontier 우선. Jev 런타임 프롬프트는 이 보정을 반영한 문구가 측정에서 나아지지 않아 이전 문구를 유지했다([보고서](tier-graphics-20261105.md)의 "리뷰 지적 재측정").
- 2026-11-05: 사용자 결정에 따라 도메인 조건(좁은 도메인 API, 공간·기하 추론, 렌더링 출력)을 balanced에서 frontier로 옮겼다. 이 정의로 그래픽 corpus를 `*-v2.jsonl`로 다시 라벨링했다. Jev 프롬프트도 같은 방향으로 바꿨다. 프롬프트는 가이드보다 넓다: "일반 UI 레이아웃·스타일은 economy" 문장이 없고, 시각 조건도 렌더링 출력으로 한정하지 않고 "visual output that tests cannot check"로 쓴다. 일반 프론트엔드 대조군 14건에서는 차이가 드러나지 않았다.
- 2026-11-06: 제품 이름만으로 frontier가 되지 않는다는 점과 Blender 프로젝트의 범용 작업 예시를 3a에 추가했다. 선택 필드 `context`를 추가했다.

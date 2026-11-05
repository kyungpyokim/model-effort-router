# 그래픽·Blender tier 기준 보정 (2026-11-05)

## 문제

그래픽, 셰이더, Blender 스크립트 요청이 대부분 `economy` tier로 분류됐다. 기존 Jev tier 기준은 작업 범위(함수·모듈 하나인가)만 봤다. 그래서 파일 하나짜리 bpy 스크립트나 셰이더는 economy가 됐다. 이런 작업의 정확성은 버전에 따라 바뀌는 좁은 도메인 API, 3D·기하 수학, 눈으로만 확인할 수 있는 결과에 달려 있다. reasoning effort를 올려도 모델이 모르는 API 지식은 생기지 않는다.

## 데이터

- `evaluation/corpus/tier-graphics-dev-v1.jsonl` 32건: 기준 문구 조정에 사용
- `evaluation/corpus/tier-graphics-holdout-v1.jsonl` 24건: 조정 후 한 번만 측정. 오답 사례는 열람하지 않음

구성은 Blender bpy, Geometry Nodes, 셰이더(GLSL·WGSL·Godot), 렌더링 결함, 3D 수학, 게임 엔진 요청이다. 대조군도 섞었다: 같은 도메인에서 값·이름·오타만 바꾸는 요청과 그래픽과 무관한 국소 작업.

AI 라벨러 두 명(서로 다른 모델)이 [라벨링 가이드](labeling-guide.md) §3a만 보고 독립적으로 role/effort/tier를 골랐다. 첫 일치는 role 55/56, effort 39/56, tier 54/56이었다. 불일치는 판정해서 `final`을 기록했다. tier 판정 결과는 dev가 economy 14, balanced 17, frontier 1이고 holdout이 economy 11, balanced 12, frontier 1이다.

한계:
- 정답은 새 tier 정의에 대한 AI 라벨러의 합의다. 사람 판정이나 실제 모델 성공률로 확인한 값이 아니다.
- 요청 문장은 합성이며 실제 사용 분포를 대표하지 않는다.
- 표본이 작고, frontier는 세트마다 1건뿐이다.

## 변경

`model_effort_router/prompts/jev_questions.json`의 tier 질문을 고쳤다.

- instructions: 도메인 지식을 판단 요소에 넣었다. effort로는 모르는 API 지식을 메울 수 없다는 점과, 도메인 단어가 아니라 실제 요구로 판단하라는 문장을 추가했다.
- `economy`: "범용 코드나 널리 쓰이는 프레임워크의 흔한 사용이고, 테스트나 요청에 적힌 값으로 결과를 확인할 수 있는 경우"로 한정했다. 지정된 값·이름·오타 변경과 널리 알려진 개념 설명은 도메인과 무관하게 economy로 명시했다.
- `balanced`: 기존 다중 모듈 조건에 하나를 더했다. 크기와 무관하게, 좁거나 버전에 민감한 도메인 API, 공간·기하 수학, 테스트로 확인할 수 없는 시각 결과가 정확성을 좌우하는 작업이다.

## 결과

Jev (`jev-latest`)로 측정했고 모든 실행에서 실패는 0건이었다. 원시 예측은 [`tier-graphics-20261105.json`](tier-graphics-20261105.json)에 있다.

| 세트 | 측정 | Role | Effort | Tier |
|---|---|---:|---:|---:|
| dev (32) | 수정 전 | 32/32 | 25/32 | 16/32 |
| dev (32) | 수정 후 | 32/32 | 25/32 | 30/32 |
| holdout (24) | 수정 전 | 24/24 | 19/24 | 13/24 |
| holdout (24) | 수정 후 | 24/24 | 19/24 | 24/24 |

수정 전 dev에서는 balanced 정답 17건 중 16건이 economy로 분류됐다. economy 정답은 모두 맞혔다. 수정 후 dev에 남은 오답은 두 건이다.
- Blender Apply Scale 설명: economy 정답을 balanced로 분류했다.
- 2D canvas 렌더러의 WebGPU 이전 계획: frontier 정답을 balanced로 분류했다. 수정 전에는 맞혔다.

balanced 조건이 넓어지면서 frontier를 끌어내릴 가능성이 있는데, frontier 표본이 적어 확인되지 않았다.

### 일반 요청 퇴행 확인

role/effort 판정이 있는 [v3 holdout](README.md) 150건을 수정 전후에 한 번씩 측정했다.

| 측정 | Role | Effort | Joint |
|---|---:|---:|---:|
| 수정 전 | 142/150 | 117/150 | 110/150 |
| 수정 후 | 142/150 | 116/150 | 109/150 |

effort가 달라진 5건 중 새로 맞힌 것이 2건, 새로 틀린 것이 3건이다. 같은 프롬프트를 반복 측정할 때의 편차(이전 기록 119와 117) 안에 있다. v3에는 tier 라벨이 없어서 분포만 비교했다. 수정 전 economy 100 / balanced 33 / frontier 17이 수정 후 99 / 33 / 18이 됐고, 바뀐 사례는 2건이다. 그래픽이 아닌 요청의 tier는 사실상 바뀌지 않았다.

## 재현

```sh
python3 -m evaluation.compare evaluation/corpus/tier-graphics-dev-v1.jsonl --backend jev --json runs/tier-graphics-dev.json
python3 -m evaluation.compare evaluation/corpus/tier-graphics-holdout-v1.jsonl --backend jev --json runs/tier-graphics-holdout.json
python3 -m evaluation.compare evaluation/corpus/role-effort-human-holdout-v3-adjudicated.jsonl --backend jev --json runs/v3.json
```

Jev API 키가 필요하고 요청 텍스트가 TypeSafe로 전송된다. 이 holdout은 이제 결과를 본 상태라, 이후 tier 기준을 다시 바꾸면 새 holdout으로 검증해야 한다.

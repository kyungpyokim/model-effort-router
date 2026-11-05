# 그래픽·Blender tier 기준 보정 (2026-11-05)

> **최종 상태**: 도메인 조건(좁은 도메인 API, 공간·기하 추론, 렌더링 출력)에 해당하는 작업은 크기와 상관없이 `frontier`로 분류한다. 사용자 결정이다. 아래 "변경"~"리뷰 지적 재측정"은 같은 조건을 `balanced`로 두던 중간 단계(v1, v2)의 기록이고, 최종 결과는 맨 아래 "frontier로 재정의" 절에 있다.

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
- 라벨링 가이드 §3a와 프롬프트의 새 기준은 같은 작성자가 함께 쓴 거의 같은 문장이다. 그래서 holdout 24/24는 대부분 "작성자의 정의와 Jev가 얼마나 일치하는가"를 잰 값이다. 경계 사례도 적다: balanced 사례는 대놓고 그래픽 작업이고, 그래픽 단어가 들어간 economy 사례는 프롬프트가 직접 예외로 적은 유형(값 변경, 이름 변경, 오타, 개념 설명)이다. "도메인 단어가 아니라 실제 요구로 판단한다"는 문장이 실제로 지켜지는지는 이 데이터로 검증되지 않는다.
- 일반 프론트엔드(UI 레이아웃·스타일) 대조군은 5건뿐이다. "테스트로 확인할 수 없는 시각 결과" 조건이 평범한 UI 작업까지 balanced로 올리는지는 충분히 확인하지 못했다.

## 변경

`model_effort_router/prompts/jev_questions.json`의 tier 질문을 고쳤다.

- instructions: 도메인 지식을 판단 요소에 넣었다. effort로는 모르는 API 지식을 메울 수 없다는 점과, 도메인 단어가 아니라 실제 요구로 판단하라는 문장을 추가했다.
- `economy`: "범용 코드나 널리 쓰이는 프레임워크의 흔한 사용이고, 테스트나 요청에 적힌 값으로 결과를 확인할 수 있는 경우"로 한정했다. 지정된 값·이름·오타 변경과 널리 알려진 개념 설명은 도메인과 무관하게 economy로 명시했다.
- `balanced`: 기존 다중 모듈 조건에 하나를 더했다. 크기와 무관하게, 좁거나 버전에 민감한 도메인 API, 공간·기하 수학, 테스트로 확인할 수 없는 시각 결과가 정확성을 좌우하는 작업이다.

## 결과

Jev (`jev-latest`)로 측정했고 모든 실행에서 실패는 0건이었다. 사례별 예측과 점수는 [`tier-graphics-20261105.json`](tier-graphics-20261105.json)에 있다. 이 파일은 실행 결과에서 점수와 예측만 추린 것이다. 지연시간 같은 필드는 빠져 있고, 모델은 alias `jev-latest`로만 기록됐다. `dev-after1`은 수정 후 유일한 dev 실행이며, 문구를 반복 조정한 기록은 없다.

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

effort가 달라진 5건 중 새로 맞힌 것이 2건, 새로 틀린 것이 3건이다. 1건 차이라 노이즈일 가능성이 크다. 다만 현재 프롬프트를 같은 조건으로 반복 측정한 편차는 아직 재지 않았다. 이전 기록의 119는 tier 질문이 추가되기 전 프롬프트에서 나온 값이라 비교 근거가 되지 않는다. v3에는 tier 라벨이 없어서 분포만 비교했다. 수정 전 economy 100 / balanced 33 / frontier 17이 수정 후 99 / 33 / 18이 됐고, 바뀐 사례는 2건이다. 그래픽이 아닌 요청의 tier는 사실상 바뀌지 않았다.

## 리뷰 지적 재측정 (v2 문구, 채택하지 않음)

독립 리뷰에서 문구 위험 두 가지가 나왔다.
1. "테스트로 확인할 수 없는 시각 결과" 조건이 평범한 UI·CSS 작업까지 balanced로 올릴 수 있다.
2. 넓어진 balanced 조건이 frontier를 끌어내릴 수 있다.

이를 고친 v2 문구를 만들어 측정했다.
- economy: 일반 UI 레이아웃·스타일은 economy라고 명시하고, "테스트나 적힌 값으로 확인 가능" 조건을 뺐다.
- balanced: "a localized task"로 한정하고, 시각 조건을 렌더링·그래픽 출력으로 좁혔다.
- frontier: 해당하면 balanced 도메인 조건보다 우선한다는 문장을 추가했다.

측정용으로 새 대조군 `evaluation/corpus/tier-frontend-controls-v1.jsonl` 22건을 만들었다. 일반 프론트엔드 작업 위주로 그래픽 도메인 작업과 frontier급 설계·계획을 섞었다. 라벨링 가이드 §3a를 위 방향으로 보정한 뒤 AI 라벨러 두 명이 독립 라벨링했다. 첫 일치는 role 22/22, effort 19/22, tier 20/22였고 판정을 거쳐 economy 16(프론트엔드 15, 일반 리팩터링 1), balanced 3(여러 모듈을 잇는 다크 모드 토글, Blender 애드온 이전 계획, Godot 셰이더), frontier 3(엔진 전체 설계·계획)이 됐다. 그래픽 dev/holdout은 보정 전 §3a로, 대조군은 보정 후 §3a로 라벨링됐다. 기존 그래픽 라벨을 다시 확인했는데(예: CSS 3D flip은 economy) 두 버전 모두와 맞았다. v1 측정에는 v1 문구가 든 별도 worktree를 썼다.

| 세트 | v1 (채택) | v2 |
|---|---:|---:|
| 그래픽 dev tier | 30/32 | 28/32 (재실행 29/32) |
| 그래픽 holdout tier | 24/24 | 22/24 |
| 대조군 tier | 22/22 | 22/22 |
| 대조군 role / effort | 22 / 15 | 22 / 15 |
| v3 role / effort / joint | 142 / 116 / 109 | 142 / 119 / 112 |

해석:
- **지적 1은 v1에서도 나타나지 않았다.** economy로 판정한 프론트엔드 대조군 15건이 v1에서 모두 economy였고, 여러 모듈을 잇는 다크 모드 토글은 balanced였다.
- **지적 2는 v2로 고쳐지지 않았다.** dev의 WebGPU 이전 계획(frontier)은 v1 한 번, v2 두 번의 실행 모두에서 balanced였다. 대조군의 frontier 3건은 v1·v2 모두 맞혔지만, 셋 다 엔진 전체를 다루는 노골적인 설계라 dev-024 같은 미묘한 frontier 사례는 판별하지 못한다. 그래픽 frontier 하향의 근거는 여전히 2건 중 1건이다. v2는 tier 라벨이 없는 v3에서 frontier를 18(v1)에서 21로 늘렸는데, 맞는 방향인지는 알 수 없다.
- **v2는 economy 예외를 약하게 만들었다.** dev의 Blender 설정 색 값 변경(economy)이 v2의 두 실행에서 모두 balanced였다. holdout에서 v2가 틀린 2건도 economy 예외 유형(normal map 설명, Godot 그림자 상수 변경)이었다. "a localized task"가 국소적인 Blender 작업을 직접 끌어올린 것으로 보인다.
- **실행 간 편차:** 같은 v2 문구로 dev를 다시 돌리자 tier 1건이 바뀌었고 effort는 바뀌지 않았다. v3 effort 116과 119의 차이도 이 편차와 프롬프트 차이를 분리할 수 없는 크기다.

그래서 프롬프트는 v1을 유지했다. 라벨링 가이드의 §3a 보정(일반 UI는 economy, frontier 우선)은 대조군 라벨의 근거이므로 그대로 둔다. v1 문구가 이 라벨과 22/22 일치하므로 프롬프트와 가이드가 실제로 어긋나는 사례는 관찰되지 않았다. frontier 하향 위험(dev-024)은 남은 과제다. frontier 사례가 더 많은 새 세트로 따로 다뤄야 한다.

## frontier로 재정의 (최종)

사용자가 그래픽·Blender 작업은 balanced가 아니라 frontier로 보내야 한다고 정했다. 그래서 도메인 조건을 balanced에서 frontier로 옮겼다. 값·이름·오타 변경과 널리 알려진 개념 설명은 그대로 economy다.

- **프롬프트**: balanced는 원래 문구(다중 모듈·서브시스템 상호작용·상태 관리·아키텍처 가이드)로 되돌렸다. frontier에 v1의 도메인 문장을 그대로 옮겼다("a task of any size whose correctness depends on ..."). economy의 예외 문장에는 "frontier에 적힌 도메인에서도"를 덧붙였다. v2에서 나빠졌던 "localized task" 표현은 쓰지 않았다.
- **라벨**: 라벨링 가이드 §3a를 새 정의로 고쳤다. 78건(dev 32, holdout 24, 대조군 22)을 `tier-*-v2.jsonl`로 복사해, 이전 라벨을 보지 않은 새 AI 라벨러 두 명이 처음부터 다시 라벨링했다. 첫 일치는 role 77/78, effort 69/78, tier 78/78이었다. role/effort 불일치는 앞 라운드에서 같은 사례를 판정한 결과와 맞췄다. 새 정답 tier는 dev가 economy 14 / frontier 18, holdout이 economy 11 / frontier 13, 대조군이 economy 15 / balanced 2 / frontier 5다.
- **채점**: 원래 문구와 v1 문구는 앞서 받은 예측을 새 정답으로 다시 채점했고, 최종 문구만 새로 호출했다.

| 세트 (v2 라벨) | 원래 문구 | v1 (도메인→balanced) | 최종 (도메인→frontier) |
|---|---:|---:|---:|
| 그래픽 dev tier | 15/32 | 13/32 | 31/32 |
| 그래픽 holdout tier | 12/24 | 12/24 | 24/24 |
| 대조군 tier | – | 19/22 | 21/22 |
| v3 150건 role / effort | 142 / 117 | 142 / 116 | 142 / 119 |

- **dev 오답 1건**: Blender Apply Scale 설명(economy)을 frontier로 분류했다. 이전 라운드에서도 경계에 있던 사례다.
- **대조군 오답 1건**: 키보드 접근성이 있는 Vue 드래그 앤 드롭 정렬(balanced)을 economy로 분류했다. economy로 판정한 일반 프론트엔드 15건은 모두 economy였고, frontier 5건(엔진 설계·계획 3건, Blender 애드온 이전 계획, Godot 셰이더)도 모두 맞혔다.
- **일반 요청 v3**: tier 분포가 원래 문구의 economy 100 / balanced 33 / frontier 17에서 98 / 32 / 20으로 바뀌었다. frontier로 올라간 3건 중 2건은 IndexedDB 로컬 사본 이전(데이터 손실)과 서명 검증 리뷰(보안)로, 기존 frontier 정의에 맞는다. 나머지 1건은 맥락 없는 "It broke again. Fix it."이다. role/effort는 떨어지지 않았다.

한계는 앞 절과 같다. 정답은 AI 라벨러의 합의이고, 기준과 프롬프트를 같은 작성자가 썼으며, holdout은 이전 라운드에서 이미 결과를 본 세트다. 따라서 24/24는 "새 정의와의 일치"이지 독립 검증이 아니다. 비용도 고려해야 한다. Claude 기본 매핑에서 그래픽·Blender 작업은 이제 Opus로 추천된다.

## 재현

```sh
python3 -m evaluation.compare evaluation/corpus/tier-graphics-dev-v2.jsonl --backend jev --json runs/tier-graphics-dev.json
python3 -m evaluation.compare evaluation/corpus/tier-graphics-holdout-v2.jsonl --backend jev --json runs/tier-graphics-holdout.json
python3 -m evaluation.compare evaluation/corpus/tier-frontend-controls-v2.jsonl --backend jev --json runs/tier-controls.json
python3 -m evaluation.compare evaluation/corpus/role-effort-human-holdout-v3-adjudicated.jsonl --backend jev --json runs/v3.json
```

Jev API 키가 필요하고 요청 텍스트가 TypeSafe로 전송된다. 이 holdout은 이제 결과를 본 상태라, 이후 tier 기준을 다시 바꾸면 새 holdout으로 검증해야 한다.

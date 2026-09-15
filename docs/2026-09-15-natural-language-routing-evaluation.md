# 자연어 모델 라우팅 비교 평가 (2026-09-15)

## 목적

구조화된 수동 facts 평가에서 나온 Codex `30/30`과 Claude 자연어 평가를 직접 비교하지 않고, 같은 26개 자연어 holdout과 수정 후 정답 라벨로 Claude Code와 Codex의 라우팅 결과를 같은 지표로 비교한다.

## 평가 조건

| 항목 | Claude Code | Codex |
|---|---|---|
| 입력 | 동일한 한·영 자연어 프롬프트 26개 | 동일한 한·영 자연어 프롬프트 26개 |
| 정답 | H05·H16 정책 결정을 반영한 수정 후 라벨 | 같은 수정 후 라벨 |
| 1차 분류 | `claude-haiku-4-5` (effort 없음) | `gpt-5.6-luna/medium` |
| 문맥 재분류 | `needs_context`일 때 `claude-sonnet-5/medium` | `needs_context`일 때 `gpt-5.6-terra/medium` |
| 호출 결과 | 26개 유효, 문맥 재분류 8개 | 26개 유효, 실패 0개, 1차 호출 28회, 문맥 재분류 4회, 재시도 2회 |
| 실행 방식 | 기존 캡처 응답을 수정 후 라벨로 재채점 | 동시성 1, 건별 제한 90초로 신규 실행 |
| 대상 코드 | `d3ae003`에서 추론 후 `16aad44`, `0187823` 정책 결정을 반영해 재채점 | `243a7437e1520837e2f76bc9b2041d73f33d5658` |

공통 채점식은 다음과 같다.

- `level 정확`: 예측 level과 정답 level이 같음
- `level ±1`: 숫자 level 차이가 1 이하임
- `과대/과소 라우팅`: 예측 level이 정답보다 높음/낮음
- `모델 일치`: 라우터가 선택한 최종 executor 모델이 정답 모델과 같음
- `안전 관련 과소`: 안전 관련 12개 중 정답보다 낮게 라우팅된 사례 수

## 결과

| 지표 | Claude Code | Codex |
|---|---:|---:|
| level 정확 | 23/26 (88.5%) | 23/26 (88.5%) |
| level ±1 | 26/26 (100%) | 25/26 (96.2%) |
| 과대 라우팅 | 2/26 (7.7%) | 3/26 (11.5%) |
| 과소 라우팅 | 1/26 (3.8%) | 0/26 (0%) |
| 모델 일치 | 24/26 (92.3%) | 24/26 (92.3%) |
| 안전 관련 과소 | 0/12 | 0/12 |

동일한 자연어 입력과 채점 기준에서는 level 정확도와 모델 일치율이 같다. 이 결과는 기존의 `Codex 30/30`과 Claude `23/26` 차이가 모델 우열보다 구조화 facts 평가와 자연어 해석 평가의 난이도 차이에서 비롯됐다는 해석을 지지한다. 이번 표에서도 Codex는 ±1 정확도와 과대 라우팅 비율이 Claude보다 좋지 않다.

## 불일치 사례

### Claude Code

| 사례 | 정답 → 결과 | 영향 | 관찰 |
|---|---|---|---|
| `H15_L2_button_style_review` | L2 → L1 | 과소, 모델 불일치 | 스타일 리뷰를 `mechanical_only=yes`로 해석했다. 안전 관련 사례는 아니다. |
| `H17_L6_mtls_design_ko` | L6 → L7 | 과대 | `needs_new_structure=yes`와 광범위 위험으로 해석했다. executor profile은 정답과 결과 모두 `claude-fable-5-1/xhigh`였다. |
| `H25_L2_show_billing_address` | L2 → L3 | 과대, 모델 불일치 | 수정 파일 수를 1개가 아닌 `2-5`로 해석해 `claude-haiku-4-5` 대신 `claude-sonnet-5/medium`을 선택했다. |

### Codex

| 사례 | 정답 → 결과 | 영향 | 관찰 |
|---|---|---|---|
| `H08_L2_db_choice` | L2 → L5 | 과대, ±1 실패 | 데이터 저장소 선택을 광범위한 새 구조 설계로 해석했다. 모델은 정답과 동일한 `gpt-5.6-sol`이었다. |
| `H17_L6_mtls_design_ko` | L6 → L7 | 과대, 모델 불일치 | mTLS 전환을 L7로 해석해 `gpt-5.6-sol` 대신 `gpt-6-astra`를 선택했다. |
| `H19_L2_internal_endpoint_field` | L2 → L3 | 과대, 모델 불일치 | 내부 endpoint의 필드 추가를 여러 파일 변경으로 해석해 `gpt-5.6-luna` 대신 `gpt-5.6-terra`를 선택했다. |

두 실행 모두 `H10_L3_config_key_rename`의 task type을 정답 `implementation`이 아닌 `local_refactoring`으로 분류했지만 level과 모델은 일치했다. 위 여섯 지표에는 task type 정확도가 포함되지 않는다.

## 실행 증거

- Codex 원본: `/tmp/model-effort-fair-ab/codex_h1_results.json`
  - SHA-256: `4b14c2ec8b001885666719479acd0d8c931c7745f664a09027ac864a70bfdb26`
  - fixture SHA-256: `5c0a1252e22e899d5abf6cfc5c38ba7850afc71ada757cb6ad3d0495f52d62b9`
  - 유효 결과: 26/26, 총 경과 시간: 550,898ms
- Claude 원본 세션: `/Users/kimkyungpyo/.claude/projects/-Users-kimkyungpyo-Workspaces-projests-model-effort-router/232c138b-d5be-4d78-ab12-46b7c5ec79c0.jsonl`
  - session id: `232c138b-d5be-4d78-ab12-46b7c5ec79c0`
  - fixture 생성 anchor: line 4804, 라벨 수정 anchor: line 5428
- Claude 보존 보고서: `/Users/kimkyungpyo/.claude/file-history/232c138b-d5be-4d78-ab12-46b7c5ec79c0/3e68d3841a5d816c@v3`
  - SHA-256: `9cc92fddb43d588fd0b06e3272c2b62474bf183b70ec3c15560d88a35f445d14`

## 한계

- 같은 것은 26개 자연어 프롬프트, 수정 후 정답 라벨, 채점식, 라우터 정책 해석이다. provider별 모델과 실행 harness는 같을 수 없으므로 순수한 단일 모델 `Luna vs Haiku` 비교가 아니다.
- Claude는 기존 응답을 재사용해 H05·H16 라벨 변경 후 재채점했고, Codex는 변경된 정책의 현재 commit에서 신규 실행했다. 따라서 동일 시점·동일 timeout의 blind A/B는 아니다.
- H05·H16 라벨은 Claude 결과를 본 뒤 정책 결정으로 수정됐으므로 이 수치는 완전히 독립된 holdout 점수로 볼 수 없다. 다음 비교에서는 라벨과 router commit을 동결한 뒤 양쪽을 새로 실행해야 한다.
- Codex의 2회 `process_failed`는 라우터 기본 재시도로 회복됐다. 최종 실패는 0건이지만, 중간 fallback을 정상 분류 성공으로 세지 않았다.
- 원본 실행 파일은 저장소 밖의 임시·로컬 경로에 있다. 이 문서는 결과 요약과 digest를 보존하지만 원본 JSONL 자체를 저장소에 복제하지 않는다.

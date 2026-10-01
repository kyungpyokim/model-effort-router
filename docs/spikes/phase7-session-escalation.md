# Phase 7 Spike — 같은 세션 모델 승격

- 기획서: [model-effort-router-pluggable-difficulty-plan.md](../plans/model-effort-router-pluggable-difficulty-plan.md) §3.2, §3.4, §11.4, §24 Phase 7-1
- 수행일: 2026-10-01 (사용자 승인 후 live 실행 3회)
- 환경: codex-cli 0.159.2, ChatGPT 구독 로그인, 파일럿 fixture 복사본, `MER_CLASSIFIER=1`(Router hook 비활성)

## 질문

`codex exec resume <id> -m <다른 모델> -c model_reasoning_effort=<effort>`로 같은 세션을 다른 모델로 이어서 실행할 수 있는가. 대화가 유지되는가. 캐시와 비용은 어떻게 되는가.

## 실행

| 회차 | 명령 | 모델 / effort | 응답 |
|---|---|---|---|
| 1 | `codex exec ... "Remember this code word: ZEBRA-42. Read shop/pricing.py ..."` | gpt-6-luna / low | 코드 워드 확인 (파일은 읽지 않음, 아래 참고) |
| 2 | `codex exec resume <id> -m gpt-6-sol -c model_reasoning_effort=high "What code word ..."` | gpt-6-sol / high | `ZEBRA-42; I didn't read any file ...` |
| 3 | `codex exec resume <id> -m gpt-6-sol -c model_reasoning_effort=high "Repeat the code word ..."` | gpt-6-sol / high | `ZEBRA-42` |

세 회차 모두 같은 `thread_id`와 같은 rollout 파일 하나에 기록됐다.

## 결과

rollout의 `turn_context`와 `token_count.last_token_usage` 기준:

| 턴 | 모델 / effort | 입력 | 캐시 적중 | 비고 |
|---|---|---:|---:|---|
| 1-a | gpt-6-luna / low | 29,737 | 18,176 | |
| 1-b | gpt-6-luna / low | 29,879 | 29,440 | |
| 2 | gpt-6-sol / high | 35,872 | 7,168 | **모델 변경 직후 캐시 대부분 끊김** |
| 3 | gpt-6-sol / high | 37,224 | 35,712 | 같은 모델에서 다시 캐시 적중 |

결론:

1. **동작한다.** `exec resume -m`으로 같은 세션의 모델·effort가 실제로 바뀐다(`turn_context`에 기록).
2. **대화가 유지된다.** 승격된 모델이 이전 턴의 내용(코드 워드, 이전 동작)을 기억했다. 저장소를 다시 탐색할 필요가 없다.
3. **모델을 바꾸면 그 턴의 캐시가 대부분 끊긴다.** 이번 예에서 약 29k가 캐시 없이 다시 읽혔다. 이후 같은 모델로 계속하면 다시 캐시된다. 승격 1회 비용 ≈ 그 시점까지 쌓인 대화 길이만큼의 미캐시 입력.
4. **`codex exec --json`의 `turn.completed.usage`는 resume 시 세션 누적값이다.** 1회차 59,616 → 2회차 95,488 → 3회차 132,712. 실행별 사용량을 구하려면 차이를 계산하거나 rollout의 `last_token_usage`를 써야 한다. 평가 도구의 exec 스트림 합산(`evaluation/usage.py::exec_stream_usage`)은 resume을 쓰는 실행에서 중복 집계할 수 있으므로 Phase 7 구현 때 고친다.

## 발견 사항

- 1회차에서 gpt-6-luna/low가 사용자 전역 `AGENTS.md`의 탐색 가이드 지침(`docs/CODEX-NAVIGATION-GUIDE.md`)을 찾다가 없자 파일을 읽지 않고 멈췄다. 사용자 전역 지침이 저가 모델의 작업 수행에 영향을 준다. 파일럿의 기준선·Router 실행도 같은 조건이었으므로 비교 자체는 공정하지만, 저가 시작 프로필의 성공률에는 영향을 줄 수 있다.
- app-server 턴 단위 변경은 `exec resume`이 동작하므로 확인하지 않았다.

## 기획서 반영

| 절 | 변경 |
|---|---|
| §3.2 | `exec resume -m` 행을 "동작(대화 유지, 모델 변경 턴은 캐시 대부분 끊김)"으로 갱신 |
| §3.4 | 승격 방식을 `codex exec resume <id> -m ... -c model_reasoning_effort=...`로 확정 |
| §22.3 / 평가 도구 | resume 사용 시 exec 스트림 사용량이 세션 누적값임을 반영 |

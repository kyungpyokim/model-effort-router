# Laya multilingual 모델 측정 (2026-10-08)

Ollama의 로컬 `laya:322m-multilingual-mlx-fp16` 모델로 v3 adjudicated 150건을 분류했다. Laya 요청의 질문 지시문을 짧게 만든 뒤 실제 warmup이 HTTP 200으로 통과했고, 이어진 150건도 모두 HTTP 200이었다. role 56/150 (37.3%), effort 30/150 (20.0%), 동시 일치 11/150 (7.3%)이다. 이 수치는 기존 다수결 라벨과의 일치율이다.

| 항목 | 결과 |
|---|---:|
| 모델 | `laya:322m-multilingual-mlx-fp16` |
| Ollama / runner | 0.40.0 / MLX, 로컬 |
| 모델 digest | `63b6e37ecedbf0bf545c1d55907326bb6bc5bed6e0aa3fcb3dd712b9a8b62024` |
| 코퍼스 | v3 adjudicated, 150건 |
| role | 56/150 (37.3%) |
| effort | 30/150 (20.0%) |
| 동시 일치 | 11/150 (7.3%) |
| 요청 성공 / 오류 | 150 / 0 |
| 왕복 지연시간 | p50 14.2 ms, p95 18.6 ms, 최대 477.4 ms |
| warmup | HTTP 200, 분류 제외 (입력 432 tokens, 출력 0) |

모든 측정 요청은 현재 project config의 `difficulty.backend: laya`, 모델 ID, `http://127.0.0.1:11434/v1/systemone`을 사용했다. warmup 1회는 점수에서 뺐고, 이후 150건을 순차 요청했다. 요청 timeout은 30초였으며 fallback은 사용하지 않았다. task와 paths만 보냈고 gold 라벨은 보내지 않았다. 모든 결과에 response model이 선택한 exact model이었다. 응답 usage 합계는 입력 76,570 tokens, 출력 0 tokens다. 이 SystemOne 응답에는 `truncated` 필드가 없어 truncation 여부는 알 수 없다. 왕복 지연시간에는 이미 로드된 서버의 요청 처리만 들어간다. 측정 중 같은 호스트에서 단위 테스트도 실행되어 전용 성능 벤치마크 조건은 아니다.

이 측정은 첫 protocol rejection 뒤에 이루어졌다. 초기 요청의 기존 role instructions는 서버 측 질문 한도 106 tokens에 대해 111 tokens여서 warmup과 후속 요청이 HTTP 400으로 거절됐다. 선택된 모델 체크포인트의 `head_max_len`은 256이다. 그 뒤 공용 Jev/Nimble 질문은 유지하고 LayaBackend에만 짧은 지시문을 적용했다. 체크포인트의 tokenizer로 센 raw instructions는 role 90→48 tokens, effort 110→58 tokens였다. 역할/effort criteria, 선택지와 `state_text` 구성은 그대로다. shared `QUESTIONS` SHA-256은 `f568c1b4a9fd93c90c7694901c775174527651c0c4decee2acd21821ea65a7e6`, 실제 Laya 질문 JSON SHA-256은 `b4aa720f535693c2e0e7609eb9d3baa3001206c9929009ff7b34d473259baa7b`다. 기존 server rejection의 원시 기록은 별도 JSON에 보존했다. 거부된 요청은 모델 정확도나 추론시간에 포함하지 않았다.

gold 분류별 role 일치는 review 23/39, fix 13/34, analysis 1/19, implementation 12/33, plan 4/18, lint 3/6, design 0/1이다. Effort 일치는 high 0/30, medium 2/24, low 16/83, xhigh 12/13이다. 전체 confusion matrix와 응답은 원시 JSON에서 확인할 수 있다. 코퍼스에 test role과 max effort gold가 없어 해당 값의 성능은 측정되지 않았다.

영어 baseline은 별도 실행 조건에서 Python Laya 0.4.0 + MPS로 측정했다. 기본 `laya` alias가 `laya-rl-agent` / `english` 체크포인트를 선택했고 role 90/150 (60.0%), effort 38/150 (25.3%), joint 30/150 (20.0%), p50 50.8 ms, p95 103.5 ms였다. 다국어 결과는 checkpoint, server/runtime, Laya 질문 지시문이 모두 다르므로 수치 차이를 언어 지원 하나의 효과로 해석할 수 없다. [영어 baseline 보고서와 원시 결과](laya-20261008.md).

v3는 다른 provider 측정에 이미 사용된 합성 코퍼스다. 라벨은 다섯 annotation sheet의 다수결이며 판정자의 독립성은 검증되지 않았다. 따라서 이 결과는 독립적인 사람 정답 정확도가 아니며, 새 요청 분포의 성능을 보장하지 않는다.

- 성공한 실행의 건별 원시 응답과 confusion matrix: [laya-multilingual-v3-20261008.json](laya-multilingual-v3-20261008.json)
- 최초 HTTP 400 시도와 서버 오류 본문: [laya-multilingual-rejected-v3-20261008.json](laya-multilingual-rejected-v3-20261008.json)
- 코퍼스 SHA-256: `9a9c4f4646452342e403a7a73815b64d36599106d7e794347343c7c44e1372ea`

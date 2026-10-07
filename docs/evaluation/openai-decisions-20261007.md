# OpenAI Decisions API role / effort evaluation

- Run: 2026-10-07
- Model: `gpt-6-luna`
- Backend: `openai_decisions`
- Method: 150 sequential requests, 30-second per-request timeout, no fallback.
- Corpus: [`role-effort-human-holdout-v3-adjudicated.jsonl`](../../evaluation/corpus/role-effort-human-holdout-v3-adjudicated.jsonl)
- Raw predictions and usage: [`openai-decisions-v3-20261007.json`](openai-decisions-v3-20261007.json)
- Code revision: `3dea669`
- Corpus SHA-256: `9a9c4f4646452342e403a7a73815b64d36599106d7e794347343c7c44e1372ea`

All 150 requests succeeded and the response parser returned valid role and effort values.

| Metric | Result |
|---|---:|
| Role exact match | 136/150 (90.7%) |
| Effort exact match | 119/150 (79.3%) |
| Joint exact match | 107/150 (71.3%) |
| Failures | 0/150 |
| p50 / max latency | 422 / 1,982 ms |
| Input / output tokens | 85,000 / 0 |
| Estimated standard token cost | $0.0085 |

The existing initial targets are role 85%, effort 80%, and joint 75%. This run cleared the role target; effort missed by one case and joint by six cases. The estimate applies GPT-6 Luna's published standard input/output token rates and is based on reported usage.

On this same corpus, the previously recorded Jev results were 141/150 role, 119/150 effort, and 111/150 joint; Nimble scored 124/150, 101/150, and 85/150. These figures are in [the v3 evaluation record](role-effort-expansion-20261006.md). The Decisions API matched Jev on effort and scored lower on role and joint in this run.

Interpret this as agreement with the corpus's five-sheet majority labels, not clean independent human accuracy. The same v3 cases were already used to report Jev and Nimble results, the independence of the label sheets is not fully verified, and the prompts are synthetic. No tuning was done on these Decisions API predictions.

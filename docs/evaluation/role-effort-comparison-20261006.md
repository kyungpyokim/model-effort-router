# Role / effort backend comparison

Run: 2026-10-06T13:13:03+09:00
Corpus: `evaluation/corpus/role-effort-v1.jsonl` (40 adjudicated synthetic cases)
Method: 40 sequential calls per backend, 30-second per-call timeout, no fallback.
Ground truth has two AI labelers; agreement before adjudication was role 38/40, effort 33/40, joint 31/40.

| Backend | Model | Cases | Role exact | Effort exact | Joint exact | p50 latency | Max latency | Failures | Input / output tokens |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| jev | `jev-latest` | 40 | 38/40 (95.0%) | 25/40 (62.5%) | 23/40 (57.5%) | 250 ms | 409 ms | 0 | 19447 / 4682 |
| nimble | `nimble` | 40 | 36/40 (90.0%) | 19/40 (47.5%) | 16/40 (40.0%) | 290 ms | 2118 ms | 0 | 25520 / 120 |

Jev used the TypeSafe API and received task text plus paths. Nimble used the local Ollama `nimble:latest` model. All 80 calls succeeded, and both backends reported usage for all 40 calls.

This is an initial synthetic benchmark, not a representative user-request sample or a human-validated holdout. Interpret the accuracy figures with that limitation.

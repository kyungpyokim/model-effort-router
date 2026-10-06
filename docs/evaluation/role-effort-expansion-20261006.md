# Role / effort corpus expansion

Run: 2026-10-06
Source: synthetic tasks in `evaluation/corpus/corpus-v3.jsonl`

## Split and labeling

- Development: 160 cases. The original 40-case role/effort pilot plus 120 distinct prompts sampled from the legacy corpus.
- Holdout: 40 distinct prompts sampled from the remaining legacy corpus. No task text overlaps the development set.
- Only `task` and `paths` were carried over. Legacy L1-L5 labels were removed and were not converted.
- Two labelers independently labeled both splits. Neither split has been adjudicated.

| Split | Cases | Role agreement | Effort agreement | Joint agreement |
|---|---:|---:|---:|---:|
| Development | 160 | 128/160 (80.0%) | 85/160 (53.1%) | 60/160 (37.5%) |
| Holdout | 40 | 35/40 (87.5%) | 21/40 (52.5%) | 18/40 (45.0%) |

Effort agreement stayed near 53% on both splits. More examples alone will not make the current accuracy figures trustworthy: the labeling criteria need calibration, and final labels need independent human review. All source tasks are synthetic, so this corpus does not establish performance on real user traffic.

## Jev / Nimble measurement

Both backends were run once on all 200 cases (40 holdout calls per backend were completed first; the remaining 160 development cases were run afterward). Requests had no fallback and all 400 calls succeeded. Because the corpus has two disagreeing AI labels and no human adjudication, these are agreement-relative scores, not validated accuracy. Scores are shown separately against each labeler; do not average them into a single accuracy number.

| Backend | Split | Reference | Role | Effort | Joint |
|---|---|---|---:|---:|---:|
| Jev | Dev 160 | labeler-a | 125/160 (78.1%) | 82/160 (51.3%) | 53/160 (33.1%) |
| Jev | Dev 160 | labeler-b | 139/160 (86.9%) | 107/160 (66.9%) | 91/160 (56.9%) |
| Jev | Holdout 40 | labeler-a | 35/40 (87.5%) | 25/40 (62.5%) | 22/40 (55.0%) |
| Jev | Holdout 40 | labeler-b | 38/40 (95.0%) | 27/40 (67.5%) | 26/40 (65.0%) |
| Jev | All 200 | labeler-a | 160/200 (80.0%) | 107/200 (53.5%) | 75/200 (37.5%) |
| Jev | All 200 | labeler-b | 177/200 (88.5%) | 134/200 (67.0%) | 117/200 (58.5%) |
| Nimble | Dev 160 | labeler-a | 119/160 (74.4%) | 59/160 (36.9%) | 32/160 (20.0%) |
| Nimble | Dev 160 | labeler-b | 134/160 (83.8%) | 69/160 (43.1%) | 54/160 (33.8%) |
| Nimble | Holdout 40 | labeler-a | 30/40 (75.0%) | 17/40 (42.5%) | 13/40 (32.5%) |
| Nimble | Holdout 40 | labeler-b | 31/40 (77.5%) | 19/40 (47.5%) | 16/40 (40.0%) |
| Nimble | All 200 | labeler-a | 149/200 (74.5%) | 76/200 (38.0%) | 45/200 (22.5%) |
| Nimble | All 200 | labeler-b | 165/200 (82.5%) | 88/200 (44.0%) | 70/200 (35.0%) |

On cases where both labelers agreed for the scored dimension, Jev matched role on 155/163 (95.1%) and effort on 82/106 (77.4%). Nimble matched role on 143/163 (87.7%) and effort on 50/106 (47.2%). The fully unanimous joint subset has only 78 cases; joint exact was Jev 53/78 (67.9%) and Nimble 22/78 (28.2%). This subset is biased toward easier-to-label cases and is not a replacement for the full holdout.

## Effort error analysis

The baseline runtime prompt in `model_effort_router/difficulty/jev.py` asked only “What reasoning effort is needed?” and sent `low`, `medium`, `high`, and `xhigh` as their own criteria; it did not include the definitions from the labeling guide. Predictions also skewed low: Nimble predicted `low` or `medium` on 164/200 cases and under-shot labeler-a 115 times versus overshooting 9 times. Jev under-shot labeler-a 76 times versus overshooting 17 times. Labeler disagreement is also material: effort labels match on only 106/200 cases. The evidence pointed to both an underspecified runtime rubric and inconsistent reference labeling; prompt tuning used dev only. A final holdout check needs human-adjudicated labels first.

## Dev-only prompt adjustment (2026-10-06)

The shared runtime rubric now defines `low` as a clear, localized task whose solution is obvious without broader context; `medium` starts when relevant context must be read or a few bounded choices considered. It keeps `high` for interacting parts, tradeoffs, or uncertain diagnosis, and `xhigh` for broad, highly uncertain work with serious consequences. Role, file count, and keywords do not determine effort. The labeling guide uses the same boundaries.

The rubric was rerun on the 160-case development split only. Match rates below compare against each AI labeler independently, not human-adjudicated truth. The prior run is the baseline on the same rows and labels.

| Backend | Labeler | Before | After |
|---|---|---:|---:|
| Jev | A | 82/159 (51.6%) | 86/159 (54.1%) |
| Jev | B | 106/159 (66.7%) | 101/159 (63.5%) |
| Nimble | A | 59/160 (36.9%) | 70/160 (43.8%) |
| Nimble | B | 69/160 (43.1%) | 82/160 (51.3%) |

Across paired cases, the `low` prediction count fell from 51/159 to 33/159 for Jev and 64/160 to 46/160 for Nimble. Jev had one provider error on `dev-086` in the new run; Nimble had none. Nimble's match rate rose against both annotators, while Jev's result was mixed, so these AI-only labels do not establish an overall Jev accuracy improvement. The holdout was not used or rerun.

### Rejected follow-up rubric trial (2026-10-06)

A follow-up prompt made the high/xhigh boundary more explicit and narrowed when context should raise effort. On the same 160 dev cases, Jev matched labeler A on 64/160 (40.0%) and B on 85/160 (53.1%); Nimble matched A on 55/160 (34.4%) and B on 71/160 (44.4%), with no provider errors. Both were lower than the prior adjusted prompt, so this wording was discarded. The runtime keeps the earlier rubric above. These references remain unadjudicated AI labels, so neither trial establishes validated accuracy. Raw predictions: `runs/role-effort-dev-rubric-v3-comparison-20261006.json`.

### Baseline expanded-run operational metrics

| Backend | Calls / failures | p50 latency dev / holdout | Input / output tokens |
|---|---:|---:|---:|
| Jev (`jev-latest`) | 200 / 0 | 241 / 237 ms | 101,246 / 23,419 |
| Nimble (`nimble`) | 200 / 0 | 304 / 299 ms | 133,730 / 600 |

## Review files

- `evaluation/corpus/role-effort-human-review-holdout.tsv`: blank human role/effort fields for all 40 holdout cases. Label this without consulting the two AI labels.
- `evaluation/corpus/role-effort-human-review-pilot.tsv`: blank human labels for the 9 pilot cases where the original two labels disagreed.
- `evaluation/corpus/role-effort-dev-v2.jsonl` and `evaluation/corpus/role-effort-holdout-v1.jsonl`: both AI labels are preserved with status `labeled`; no `final` labels are present.

After the 40 holdout cases have human labels, adjudicate them and rerun Jev and Nimble on that held-out split for a human-referenced result. Use the development set to revise the guide or tune routing, not to report final accuracy.

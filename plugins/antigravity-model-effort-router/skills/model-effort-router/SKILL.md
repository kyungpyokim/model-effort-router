---
name: model-effort-router
description: Classify a coding task by difficulty from L1 to L5 and choose the closest available Antigravity model/effort variant. Use when the task should be routed by scope, ambiguity, diagnosis, design, risk, and verification complexity before execution.
---

# Model Effort Router

Score the task using `references/routing-policy.md` and report the selected level. Antigravity effort is embedded in model names, so use `agy-route` to launch a new session with the matched model when execution under that profile is required.

Do not claim the current running session changed models merely because a route was recommended.

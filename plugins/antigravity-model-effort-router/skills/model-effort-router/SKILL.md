---
name: model-effort-router
description: Classify a coding task by difficulty from L1 to L5 and choose the closest available Antigravity model/effort variant. Use when the task should be routed by scope, ambiguity, diagnosis, design, risk, and verification complexity before execution.
---

# Model Effort Router

Do not score the task in the current session. Resolve the included router
relative to this file and run `python3 ../../scripts/router.py "<task>" --platform antigravity --detect-antigravity-models --format json`. Report that
fixed native `gemini-3.6-flash-low` preflight result, including any fallback. Antigravity effort is
embedded in model names, so use `agy-route` to launch a new session with the
matched model when execution under that profile is required.

Do not claim the current running session changed models merely because a route was recommended.

---
name: route
description: Classify a coding task by difficulty from L1 to L7 (or Critical Override) and choose the closest available Antigravity model/effort variant. Use when the task should be routed by scope, ambiguity, diagnosis, design, risk, and verification complexity before execution.
---

# Model Effort Router

Do not score the task in the current session. Resolve the included router
relative to this file and run `python3 ../../scripts/router.py "<task>" --platform antigravity --detect-antigravity-models --format json`. Antigravity effort is
embedded in model names, so immediately delegate the complete task to the
matching L1-L7 or Critical plugin agent. Pass the complete generated route JSON along with
the original task. The delegated executor must use every
`verification.recommended` ID and reason to select applicable existing
repository checks and report each result or why it was not run.

Do not describe the current session's model or attempt to change it. When named-agent delegation is unavailable, use `../../bin/agy-route -- "<task>"` to run the selected profile in a new session, then do not continue the task in the parent session.

Schema v3 `orchestration_eligible` is future metadata only.
`scripts/astra_adapter.py` is caller-invoked and digest-verified; respect
`execution_strategy: direct` because direct v2 and v3 route-file replay never invokes it.

The result's `verification` object is recommendation metadata only. The
selected executor receives recommended IDs and reasons, selects applicable
existing repository checks, and reports results or why a check was not run.
Do not treat it as executed output or add it to a replay command.

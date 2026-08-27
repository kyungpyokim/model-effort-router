---
name: route
description: Classify a coding task by difficulty from L1 to L5 and choose the closest available Antigravity model/effort variant. Use when the task should be routed by scope, ambiguity, diagnosis, design, risk, and verification complexity before execution.
---

# Model Effort Router

Do not score the task in the current session. Resolve the included router
relative to this file and run `python3 ../../scripts/router.py "<task>" --platform antigravity --detect-antigravity-models --format json`. Antigravity effort is
embedded in model names, so immediately delegate the complete task to the
matching L1-L5 plugin agent. Pass the complete generated route JSON along with
the original task. The delegated executor must use every
`verification.recommended` ID and reason to select applicable existing
repository checks and report each result or why it was not run.

Do not describe the current session's model or attempt to change it. When named-agent delegation is unavailable, use `../../bin/agy-route -- "<task>"` to run the selected profile in a new session, then do not continue the task in the parent session.

The result's `verification` object is recommendation metadata only. The
selected executor receives recommended IDs and reasons, selects applicable
existing repository checks, and reports results or why a check was not run.
Do not treat it as executed output or add it to a replay command.

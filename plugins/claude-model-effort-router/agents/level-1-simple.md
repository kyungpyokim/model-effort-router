---
name: level-1-simple
description: Use for a narrow, reversible, well-specified task.
model: sonnet
effort: low
maxTurns: 12
---

Execute only the explicitly scoped task. Prefer direct edits and focused checks.

Do not invoke the model-effort router recursively. If the task must be escalated, stop and return the evidence plus the recommended higher level to the parent agent.

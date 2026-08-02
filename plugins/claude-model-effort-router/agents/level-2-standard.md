---
name: level-2-standard
description: Use for a clear feature, focused bug fix, or module-level task with a total difficulty score of 3-5.
model: sonnet
effort: medium
maxTurns: 24
---

Implement the bounded task using existing project patterns. Add focused tests and keep changes localized.

Do not invoke the model-effort router recursively. If the task must be escalated, stop and return the evidence plus the recommended higher level to the parent agent.

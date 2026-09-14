---
name: level-3-complex
description: Use for multi-file implementation, non-trivial debugging, or broad refactoring.
model: sonnet
effort: high
maxTurns: 40
---

Investigate dependencies and failure paths, implement in coherent steps, and run integration or regression checks.

Do not invoke the model-effort router recursively. If the task must be escalated, stop and return the evidence plus the recommended higher level to the parent agent.

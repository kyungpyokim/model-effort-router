---
name: effort-xhigh
description: Route executor with xhigh reasoning effort. Selected by the model-effort router from the matrix effort; do not pick it manually.
effort: xhigh
---

Follow the route instructions at the top of the prompt and do only the assigned work.

Do not invoke the model-effort router recursively. If the task must be escalated, stop and return the evidence plus the recommended higher level to the parent agent.

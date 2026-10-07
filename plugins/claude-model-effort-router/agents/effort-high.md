---
name: effort-high
description: Model Effort Router worker with high reasoning effort. Chosen by the router hook advice; pass the model with the Agent call's model parameter. Use only when the model-effort-router hook advice names this agent.
effort: high
---

Do only the work described in the Context Packet. Do not invoke the model-effort-router recursively. If the task needs more effort than high, stop and return the evidence gathered plus the recommended higher effort to the parent.

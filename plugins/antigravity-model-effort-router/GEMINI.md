# Model Effort Router

When the user invokes `/route`, classify the task using `references/routing-policy.md` and report the selected L1-L5 profile.

Antigravity exposes effort as part of the model choice. A running extension command cannot reliably replace the current session model, so use `agy-route` to perform deterministic model selection before the target session starts.

Do not claim that merely printing a recommendation has switched the model. When work must execute under the selected profile, launch a routed session with `agy-route`.

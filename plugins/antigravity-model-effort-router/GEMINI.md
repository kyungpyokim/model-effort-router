# Model Effort Router

When the user invokes `/route`, do not classify the task in the current
session. Run `python3 <extension-root>/scripts/router.py "<task>" --platform antigravity --detect-antigravity-models --format json` and report its fixed
native `gemini-3.6-flash-low` preflight result.

Antigravity exposes effort as part of the model choice. A running extension command cannot reliably replace the current session model, so use `agy-route` to perform deterministic model selection before the target session starts.

Do not claim that merely printing a recommendation has switched the model. When work must execute under the selected profile, launch a routed session with `agy-route`.

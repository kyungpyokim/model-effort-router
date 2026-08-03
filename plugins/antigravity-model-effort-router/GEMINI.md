# Model Effort Router

When the user invokes `/route`, do not classify the task in the current
session. Run `python3 <extension-root>/scripts/router.py "<task>" --platform antigravity --detect-antigravity-models --format json` and report its fixed
native `gemini-3.6-flash-low` preflight result.

Antigravity exposes effort as part of the model choice. A running extension command cannot reliably replace the current session model, so launch the matching L1-L5 plugin agent in a new session through `agy-route` before work starts.

Do not claim that merely printing a recommendation has switched the model. Delegate the complete task to the matching plugin agent; `agy-route` supplies both `--agent` and the selected model for its new session.

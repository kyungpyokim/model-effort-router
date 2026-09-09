# Model Effort Router

When the user invokes `/route`, do not classify the task in the current
session. Run `python3 <extension-root>/scripts/router.py "<task>" --platform antigravity --detect-antigravity-models --format json --interactive` once and save stdout unchanged to a fresh temporary `<route.json>` file. Report the generated route, whose primary classifier is native `Gemini 3.8 Flash (Medium)` with a `Gemini 3.1 Pro (High)` fallback when needed.

Antigravity exposes effort as part of the model choice. A running extension command cannot reliably replace the current session model. Execute the saved `steps[].command` through `<extension-root>/bin/agy-route --route-file "<route.json>"` before work starts. This preserves L1-L7 and Critical profiles and both single and two_stage routes without reclassification or model detection.

Do not claim that merely printing a recommendation has switched the model. Do not continue the task in the parent session after launching the saved route.

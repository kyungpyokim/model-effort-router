# Model-Effort Router for Antigravity

A native Antigravity plugin packaging the shared routing core and an interactive `mer chat` entry point.

## Use

`python3 "$HOME/.gemini/antigravity-cli/plugins/model-effort-router/bin/mer" chat 'Fix the parser bug'` after CLI installation. From a workspace IDE install, run `python3 .agents/plugins/model-effort-router/bin/mer chat 'Fix the parser bug'` at the workspace root. The command classifies the request using the configured backend and starts Antigravity at the selected model and effort. The interactive conversation is yours from there; later turns are not rerouted.

For a manual profile, add this to `.model-effort-router.json`:

```json
{"router":{"mode":"manual"}}
```

Then use a first-line override:

```text
/router session=balanced:medium
Fix the parser bug
```

To preview without a classifier call, use `mer chat --dry-run --level L3 'Fix the parser bug'`.

## Current support

Economy is Gemini 3.8 Flash, balanced is Claude Sonnet 5.5, and frontier is Claude Opus 5.5. Available medium/high effort is encoded in each model slug. `xhigh` requests use the available high profile and retain the original request in the report.

The default subscription classifier is disabled on this host until tool isolation is verified. Automatic routing may use configured Jev or loopback-only Nimble. Automated `mer run`, resume/escalation, independent review, and plan/review-only sessions remain unavailable. The host adapter does not claim that Antigravity plan mode enforces read-only access. No lifecycle hook is installed: the observed transcript does not expose a verified complete raw user-turn boundary.

## Install

Validate locally with `agy plugin validate plugins/antigravity-model-effort-router`. After review, install from the repository using `agy plugin install ./plugins/antigravity-model-effort-router`. The latter changes the current user's Antigravity plugin installation.

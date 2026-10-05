`model_effort_router/` is the single source of truth for runtime code. Plugin
directories contain only host integration, manifests, hooks, skills, and
launchers; do not copy the runtime package into them.

After changing the core, install it from this checkout with
`python3 scripts/install_core.py`. Verify the installed runtime with
`python3 scripts/install_core.py --check`. For local tests and development,
set `MER_CORE_PATH` to the repository root.

Navigation pointers:

- Execution flow: `model_effort_router/flow.py`
- Plugin entrypoint facade: `model_effort_router/entrypoints.py`
- Host declarations: `plugins/*-model-effort-router/router.py`
- Review prompts and verdict parsing: `model_effort_router/review.py`
- Test-without-change probe: `model_effort_router/gate/probe.py`
- Session review policy: `model_effort_router/policy/session.py`
- Risk patterns: `model_effort_router/difficulty/risk.py`

Retro: feed human review findings back into the next agent run.

- A finding that comes up twice in human review becomes a one-line rule here.
- If a test, lint or `scripts/` check can catch it deterministically, add the check instead and drop the rule.
- If an agent got lost looking for a file, add a navigation pointer above.
- Delete lines that no longer hold. One rule per line, with a short reason.

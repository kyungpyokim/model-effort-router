`model_effort_router/` is the single source of truth for runtime code. Plugin
directories contain only host integration, manifests, hooks, skills, and
launchers; do not copy the runtime package into them.

After changing the core, install it from this checkout with
`python3 scripts/install_core.py`. Verify the installed runtime with
`python3 scripts/install_core.py --check`. For local tests and development,
set `MER_CORE_PATH` to the repository root.

Navigation pointers:

- Execution flow: `model_effort_router/flow.py`
- Review prompts and verdict parsing: `model_effort_router/review.py`
- Session review policy: `model_effort_router/policy/session.py`
- Risk patterns: `model_effort_router/difficulty/risk.py`

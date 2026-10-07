# OpenCode plugin and router eligibility

## Delivered

- Expanded shared task targeting so technical OpenCode/plugin planning requests match code context and Korean `계획` matches intent.
- Registered OpenCode for advice routing with configurable execution/reasoning model profiles. Defaults are OpenCode Zen's `opencode/mimo-v2.6-flash-free` and `opencode/nemotron-3-ultra-free`; availability can change.
- Added the `plugins/opencode-model-effort-router/` local plugin bundle. Its `route_advice` tool calls the shared runtime with task, role, effort, and project cwd; it does not change the active model or run workers.
- Rejected `mer run --host opencode` explicitly because worker execution safety and output contracts are unverified.
- Documented local setup. The bundle pins stable `@opencode-ai/plugin` 1.18.35 because the published SDK exports do not currently match the V2 custom-tool API described in V2 docs.

## Verification

- Targeting/core and plugin bundle regression tests.
- Bun route tool tests with a stubbed subprocess; no model/provider call.
- `python3 scripts/install_core.py` and `python3 scripts/install_core.py --check`.
- Full suite and final diff checks.

## Deferred

Automatic model switching and OpenCode worker execution require a verified host contract. The plugin does not modify OpenCode configuration; users add the documented project-local plugin path themselves.

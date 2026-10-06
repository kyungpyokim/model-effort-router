# Jev-Selected Active-Turn Routing Implementation Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task by task. Steps use checkbox syntax for tracking.

**Goal:** Apply Jev's selected model and reasoning effort to the current Codex turn automatically, without requiring the user to invoke `mer`.

**Architecture:** Keep the existing `UserPromptSubmit` classification and profile selection. After classification, send the selected model and effort to the running Codex app-server with its turn-scoped `turn/settings/update` request, then return the existing advisory context. Never start a second Codex session; if the live update cannot be applied, keep the current advisory behavior.

**Tech Stack:** Python standard library; Codex app-server JSON-RPC proxy; existing Router Core policy and host adapter.

**Spec:** User request in this conversation; current behavior and constraints are in `plugins/codex-model-effort-router/README.md` and `model_effort_router/host/codex_hooks.py`.

## Global Constraints

- `model_effort_router/` remains the only runtime source of truth.
- Keep hook failures fail-open; a failed update must not block the submitted prompt.
- Apply settings to the current turn only; do not change future thread defaults.
- Do not change Codex user configuration automatically or enable experimental flags silently.
- Add no third-party dependencies.
- Keep the existing `mer chat` and `mer run` behavior unchanged.

---

### Task 1: Prove the live Codex turn update works

**Files:**
- No repository changes. Use a disposable Codex thread and the installed app-server protocol.

**Interfaces:**
- Input: Codex `UserPromptSubmit` payload with `session_id` and `turn_id`.
- Operation: initialize `codex app-server proxy` with experimental API support, then call `turn/settings/update` with the corresponding thread and turn IDs, selected `model`, and `effort`.
- Success: response confirms `applied`, and the turn records the selected profile.

- [ ] Confirm Codex sends usable `session_id` and `turn_id` to a synchronous `UserPromptSubmit` hook.
- [ ] On a disposable session, enable `step_model_switching` only in its isolated Codex configuration and restart that session.
- [ ] Call `turn/settings/update` before the model responds; verify the selected model and effort apply to this turn and the next turn retains its prior defaults.
- [ ] Stop here if the proxy cannot reach the active desktop session, the update is rejected, or it misses the current model step. Keep the hook advisory until a supported host path is available.

**Gate:** This API is experimental. In the local Codex CLI 0.160.0, `step_model_switching` is marked under development and disabled by default. Model updates require that feature, so live behavior must be proven before implementation; any user-wide opt-in and app restart require explicit user choice. See the [Codex app-server protocol](https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/src/protocol/v2/turn.rs) and [feature list](https://github.com/openai/codex/blob/main/codex-rs/core/src/features.rs).

### Task 2: Add a small app-server request helper

**Files:**
- Create: `model_effort_router/host/codex_app_server.py`
- Create: `tests/test_codex_app_server.py`

**Interfaces:**
- `apply_turn_settings(thread_id: str, turn_id: str, model: str, effort: str, *, timeout_s: float = 2.0) -> bool`
- Return `True` only when the matching JSON-RPC response confirms the update was applied; return `False` for unavailable targets or a bounded transport/protocol failure.

- [ ] Write one unit test using a fake `codex app-server proxy` process that verifies initialize, `initialized`, and turn update messages, including response-ID matching.
- [ ] Write failure tests for timeout, malformed output, protocol error, and `targetUnavailable`; assert the helper does not report success.
- [ ] Implement the minimal stdlib JSON-RPC exchange, stop the child process on every path, and cap the request to two seconds.
- [ ] Run `python3 -m unittest tests.test_codex_app_server -v`.

### Task 3: Apply the selected profile from the hook

**Files:**
- Modify: `model_effort_router/host/codex_hooks.py`
- Modify: `model_effort_router/host/advice.py`
- Modify: `tests/test_user_prompt_submit.py`
- Modify: `plugins/codex-model-effort-router/README.md`
- Modify: `plugins/codex-model-effort-router/skills/mer/SKILL.md`

**Interfaces:**
- Reuse `route()`, `session_plan()`, and the Codex host adapter to select and resolve the profile. Do not classify the prompt twice.
- Attempt an update only for a routed Codex prompt with valid thread and turn IDs. Respect `/router off` and `no_route`; in manual mode, apply only an explicit valid session override.
- For `route`, apply `sp.start`; for `plan_only`, apply `sp.plan_profile`; for `review_only`, apply `sp.review` or `REVIEW_DEFAULT`.

- [ ] Add hook tests proving the update receives Jev's mapped model and effort for each routed target, and no update happens for `no_route`, `/router off`, manual mode without an explicit session override, or missing IDs.
- [ ] Add tests proving success says the profile was applied to this turn, while update failure retains the recommendation and still returns normal hook context.
- [ ] After the tests fail for the new cases, call the helper once after profile resolution and before rendering advice; keep update errors local so they fall back to advisory output.
- [ ] Record only apply status and selected profile in the existing route log; do not log prompt text or raw subprocess errors.
- [ ] Update the README and skill to describe automatic per-turn application, experimental feature requirements, and advisory fallback.
- [ ] Run `python3 -m unittest tests.test_codex_app_server tests.test_user_prompt_submit -v`, then `python3 -m unittest discover -s tests` and `python3 scripts/install_core.py --check`.

### Task 4: Verify in the Codex app

**Files:**
- No additional repository changes unless the spike exposes a protocol mismatch.

- [ ] With explicit opt-in to `step_model_switching` and after restarting Codex, submit a small request from the normal app UI.
- [ ] Verify the hook log reports an applied profile and the current turn uses the Jev-selected model and effort.
- [ ] Submit a second prompt and verify it is independently routed; submit `/router off` and verify the active model is left alone.
- [ ] Disable the feature or simulate a proxy failure and verify the prompt continues with advisory context and no blocked turn.

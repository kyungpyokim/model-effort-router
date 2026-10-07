# Codex Routed Delegation Plan

> **For agentic workers:** Use `subagent-driven-development` or `executing-plans` to implement this plan task by task.

**Goal:** Check whether Codex can prevent Main from editing before the routed Subagent starts, then implement only the enforcement the hook API can reliably support. Keep Main as the orchestrator; MER must not create retries or recursive routing.

**Scope:** This can at most gate observable code-changing tool calls. It cannot force delegation for read-only analysis unless Codex exposes a separate reliable completion gate. Do not describe the result as universal enforcement.

**Architecture:** First inspect the installed Codex hook contract and verify it in a disposable session. A gate is feasible only if a dispatch can be mapped to the selected child by a proven identity bridge, the host can reliably deny the relevant edits, and those signals are usable despite event ordering. Matching parent and child `turn_id` values alone is not dispatch correlation. Until a current-version probe verifies these signals, keep the hook advisory-only and do not implement a partial gate. Hooks never start agents, resubmit prompts, or retry classification.

**Runtime:** Shared Python package under `model_effort_router/`; Codex hook manifest and launcher under `plugins/codex-model-effort-router/`; `unittest`.

## Constraints

- Shared runtime remains the single source of truth. Plugin folders contain host integration only.
- Never persist raw prompts or private reasoning. Keep only IDs, prompt fingerprint, route fields, status, and validated dispatch correlation data.
- Preserve no-route and `router.mode=off|manual` behavior. Child sessions and events without a reliable turn identity are outside the managed gate and must not be mistaken for parent turns.
- Apply terminal failure only to a positively identified managed turn. Missing state, missing IDs, direct/off/manual routes, or child events must not poison unrelated turns.
- A hook denial is not proof that the model stops retrying. MER must not retry; repeated model tool calls remain Codex-controlled and must continue to be denied while the route is pending.
- The gate may only claim that the requested dispatch matches the configured role/model/effort when those values are visible and validated. If actual Subagent model or effort cannot be observed, state that limitation and do not claim runtime model compliance.
- After changing shared core code, run `python3 scripts/install_core.py` and `python3 scripts/install_core.py --check`.

## Files

- Inspect and, if feasible, modify `model_effort_router/host/codex_hooks.py` and `model_effort_router/entrypoints.py` for lifecycle event dispatch and state handling.
- If feasible, add `model_effort_router/host/codex_route_state.py` for compact per-turn state and concurrency control.
- Update `plugins/codex-model-effort-router/hooks/hooks.json` and its launcher so the event name from stdin reaches the correct handler. Keep `UserPromptSubmit` as the compatibility default only for callers without an event name; validate event names against an allowlist and read stdin once.
- Update `plugins/codex-model-effort-router/skills/classify/SKILL.md` and `README.md` to state Main's workflow and the proven enforcement boundary.
- Add focused tests in `tests/test_codex_route_state.py` and `tests/test_codex_pre_tool_use.py`; extend `tests/test_user_prompt_submit.py`, `tests/test_entrypoints.py`, and `tests/test_plugin_bundle.py`.

## Task 1: Verify the host enforcement contract — NO-GO for implementation

- [x] Read the official Codex hooks reference and inspect the installed plugin manifest, launcher, `entrypoints.hook()`, `host/codex_hooks.py`, and existing hook tests.
- [x] In a disposable session on Codex CLI 0.160.1, probe a real Subagent dispatch and a harmless `apply_patch` call. `PostToolUse` for `collaborationspawn_agent` arrived before `SubagentStart` in this run. Its response contained `task_name: /root/probe`; `SubagentStart` contained a separate `agent_id` and child `turn_id`, with no task name or dispatch `tool_use_id`. The two events therefore have no direct stable identity bridge. Do not infer identity from ordering or timing.
- [x] Record current evidence: the live `PreToolUse` hook returned deny for `apply_patch`, and Codex blocked the harmless edit. This proves denial works for this supported tool call in this probe, not for every code-changing path. The documented `SubagentStart` schema has no dispatch `tool_use_id` and says the event cannot prevent the child from starting. No effort field is documented. Tool hooks do not cover every possible code change. Therefore the current result remains advisory-only: Main must follow routing advice; no read-only delegation or universal code-edit enforcement is claimed.
- [x] Defer Tasks 2–4: the 0.160.1 live probe found no reliable dispatch→child identity bridge, so a gate cannot safely know that the selected worker started. The observed event order is only one run and does not create that bridge. Model was visible as the parent turn's `gpt-6-luna`; the probe did not verify the child model or effort. Keep model/effort compliance advisory.
- [x] Update the classify skill and README documentation with the 0.160.1 live evidence, Main's responsibilities, and the verified limitation. Stop after documentation; do not add routing state, event hooks, or an edit gate.

## Task 2: Add race-safe managed-turn state (deferred; only if Task 1 later passes)

Files: add `tests/test_codex_route_state.py` and `model_effort_router/host/codex_route_state.py`.

- [ ] Write tests first for claim-once behavior, duplicate route delivery, allowed transitions (including explicit terminal recovery), session/turn isolation, unsafe IDs, bounded lock waits, and competing hook processes.
- [ ] Implement per-turn exclusive claim/locking around the full read → classify → persist sequence. `os.replace` alone is insufficient. Reuse an existing project locking convention if available; otherwise use a standard-library mechanism supported by the target runtime. Bound lock waits within the hook timeout; never steal an active classifier's claim or classify again after a wait expires. Validate IDs and derive filesystem-safe state keys from the session/turn pair; never interpolate raw IDs into paths.
- [ ] Represent only the necessary states: `classifying`, `direct`, `routed`, `dispatch_pending`, `delegated`, `terminal`. Define crash behavior: an abandoned `classifying` claim becomes a fixed terminal outcome; never silently reclassify it. A failure before a routed decision is persisted remains ungated because the turn may have been direct. Preserve whether a terminal outcome belongs to a confirmed routed turn. Atomic writes protect file integrity but do not replace the lock.
- [ ] Add tests for interruption/abandoned claims and state-transition races. Do not promise exactly-once classification across process crashes unless the claim protocol proves it.

Run: `MER_CORE_PATH="$PWD" python3 -m unittest tests.test_codex_route_state`

## Task 3: Memoize one route decision per managed turn (deferred; only if Task 1 later passes)

Files: modify `model_effort_router/host/codex_hooks.py`; extend `tests/test_user_prompt_submit.py`.

- [ ] Test duplicate hook delivery using the same explicit `session_id` and `turn_id`. Assert the returned advice is stable, the route log is read with that same session ID, and the fake classifier was called once (route-log count alone does not prove classifier call count).
- [ ] Under the Task 2 lock/claim, classify and persist the compact route or `direct` result. If IDs are missing, do not create managed state; retain the current advisory behavior and record only a privacy-safe fixed error if appropriate.
- [ ] Do not parse transcript files. Main uses its active context to prepare the Subagent packet.

Run: `MER_CORE_PATH="$PWD" python3 -m unittest tests.test_user_prompt_submit`

## Task 4: Correlate the routed dispatch and gate edits (deferred; only if Task 1 later passes)

Files: modify `model_effort_router/host/codex_hooks.py` and `plugins/codex-model-effort-router/hooks/hooks.json`; add `tests/test_codex_pre_tool_use.py`.

- [ ] Test policy for pending routed turns, matching dispatch, matching `SubagentStart`, direct/off/manual turns, child sessions, missing IDs/state, mismatched dispatch settings, and repeated denied edit calls.
- [ ] Accept a dispatch as satisfying the route only when it identifies the selected worker and every observable route field matches the stored route. Validate role/model/effort when exposed; unavailable model/effort fields limit the guarantee as documented in Task 1. Mark `dispatch_pending` with the dispatch correlation ID; mark `delegated` only when `SubagentStart` matches that ID and parent turn. If the host does not expose enough fields to identify and correlate the selected worker, Task 1 should have stopped this implementation path.
- [ ] Deny recognized code-changing tools for a managed `routed`/`dispatch_pending` turn until a matching Subagent starts. Continue denying every repeated edit attempt while pending; do not make denial one-shot. Allow edits after matching delegation. Do not classify repeated valid worker dispatches as terminal unless the host contract proves they are invalid.
- [ ] For a confirmed routed turn, `terminal` continues to deny edits; unrelated direct/child turns and pre-route failures remain ungated. Allow dispatch tools needed to recover, and release the gate only after a valid correlated start. Define and test that recovery transition explicitly.
- [ ] Define gate read/parse/lock failure behavior explicitly. Existing catch-all fail-open handling in `codex_hooks.main()` and `entrypoints.hook()` must not silently override an edit denial for a confirmed routed turn. Test failure propagation through the real launcher; if an error prevents identifying the turn as routed, retain advisory behavior and document that failure boundary.
- [ ] Verify in a disposable session that denial blocks the edit, that normal Subagent dispatch still works, and that repeated denied calls do not create MER retries or recursive classification.

Run: `MER_CORE_PATH="$PWD" python3 -m unittest tests.test_codex_pre_tool_use tests.test_codex_route_state`

## Task 5: Wire events, document the boundary, and verify (documentation-only under current NO-GO)

Files under current NO-GO: `README.md`, `plugins/codex-model-effort-router/skills/classify/SKILL.md`, `plugins/codex-model-effort-router/README.md`. Runtime wiring, manifest, and tests remain deferred unless Task 1 later passes.

- [ ] Only after a later Task 1 pass: add an allowlisted event dispatcher that reads hook stdin once and forwards the event name to the shared handler; keep the existing `UserPromptSubmit` default for legacy direct callers and test launcher wiring.
- [ ] Only after a later Task 1 pass: register events proven by the disposable probe.
- [x] Document Main's route → packet → matching Subagent dispatch → integrate sequence and the current boundary: Main is responsible for following advice; hooks cannot force read-only delegation or universally enforce code edits. Actual model/effort compliance is not claimed without enforceable signals.
- [x] Leave advisory runtime behavior unchanged because Task 1 prerequisites are not verified.

If implementing the gate, run:

```sh
MER_CORE_PATH="$PWD" python3 -m unittest tests.test_user_prompt_submit tests.test_codex_route_state tests.test_codex_pre_tool_use tests.test_entrypoints tests.test_plugin_bundle
python3 scripts/install_core.py
python3 scripts/install_core.py --check
MER_CORE_PATH="$PWD" python3 -m unittest discover
```

## Acceptance criteria

- The outcome matches the verified Codex hook contract; no unsupported guarantee is claimed.
- When the gate becomes feasible, duplicate/concurrent events do not independently classify the same managed turn, and only a proven-correlated routed Subagent start releases code-edit tools.
- Direct, no-route, off/manual, child, and missing-ID cases retain defined non-poisoning behavior.
- Repeated denied calls remain denied; MER never retries, recursively routes, or resubmits.
- No raw prompts or private reasoning are persisted.
- The launcher forwards registered events and preserves legacy `UserPromptSubmit` callers.
- If Codex cannot provide the required signals, only the documented feasibility result is delivered; no partial gate is installed.

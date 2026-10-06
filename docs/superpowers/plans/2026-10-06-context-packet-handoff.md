# Main-to-Subagent Context Packet Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make MER's Main guidance explicitly build a populated, minimal Context Packet from the current request and relevant conversation context, then include it in the native Subagent invocation.

**Architecture:** MER cannot inspect Main's private conversation state or invoke a native Subagent. The shared hook can only provide instructions; Main constructs the packet and passes it through the host's native Subagent prompt. Keep this as a guidance contract with tests for the emitted instructions; do not add a runtime context-capture or dispatch layer.

**Tech Stack:** Python, unittest, Markdown plugin skills and READMEs.

**Spec:** User request and clarifications in this conversation (2026-10-06); no separate spec document.

## Global Constraints

- Main's model and settings do not change.
- Never forward the full conversation or private implementation reasoning by default.
- Implementation packets contain populated task, context, decisions, constraints, relevant files, and expected result.
- Review packets contain goal, decisions, constraints, actual diff, and verification status/results; do not invent checks that were not run.
- Preserve Antigravity's host-supported execution limitation.
- Do not claim that MER guarantees native Subagent invocation or packet contents; Main remains responsible for both.
- Do not change `mer run` packet generation; it cannot access Main's conversation and is a separate worker path.

---

### Task 1: Make hook advice require a populated packet handoff

**Files:**
- Modify: `model_effort_router/host/advice.py`
- Test: `tests/test_user_prompt_submit.py`

- [x] **Step 1: Extend the hook contract test**

Add assertions to `test_advisory_includes_role_effort_model_and_context_packet` that normal advice tells Main to derive packet content from the current request and relevant conversation, populate the fields, and include the completed packet in the native Subagent invocation message. Assert it says not to forward the full conversation/private reasoning.

- [x] **Step 2: Verify the test fails**

Run: `python3 -m unittest tests.test_user_prompt_submit.UserPromptSubmitTest.test_advisory_includes_role_effort_model_and_context_packet`

Expected: FAIL because current advice lists packet field names but does not explicitly require a populated packet in the Subagent invocation.

- [x] **Step 3: Update the advice text**

In `advice.render`, tell Main to build the populated packet from available request/conversation facts and pass it directly to the native Subagent call. For review, require the current diff and actual verification results/status. Keep the selected role/model/effort guidance and the statement that Main's active model is unchanged.

- [x] **Step 4: Verify the focused test passes**

Run: `python3 -m unittest tests.test_user_prompt_submit.UserPromptSubmitTest.test_advisory_includes_role_effort_model_and_context_packet`

Expected: PASS.

### Task 2: Align host skills and user docs with the handoff contract

**Files:**
- Modify: `plugins/codex-model-effort-router/skills/mer/SKILL.md`
- Modify: `plugins/claude-model-effort-router/skills/mer/SKILL.md`
- Modify: `plugins/antigravity-model-effort-router/skills/mer/SKILL.md`
- Modify: `README.md`
- Modify: `README.ko.md`

- [x] **Step 1: Correct the hook description**

State that the hook supplies packet fields/instructions, not a completed packet containing the current conversation. Main populates the packet and includes it in the host-native Subagent invocation.

- [x] **Step 2: Document packet contents and limits**

For implementation, include only relevant request context, decisions, constraints, files, and expected result. For review, include goal, decisions, constraints, diff, and verification status/results. Mark checks as not run when applicable; omit private implementation reasoning and unrelated conversation.

- [x] **Step 3: Keep host and worker behavior accurate**

Clarify that native Subagent dispatch is Main's responsibility; `mer run` is a separate one-worker path and cannot read Main's conversation. Preserve Antigravity's restriction to host-supported Subagent execution.

### Task 3: Verify the guidance contract

**Files:**
- Test: `tests/test_user_prompt_submit.py`
- Verify: all changed skill/README docs and installed shared runtime

- [x] **Step 1: Run focused hook tests**

Run: `python3 -m unittest tests.test_user_prompt_submit`

Expected: PASS.

- [x] **Step 2: Run the full unit suite**

Run: `python3 -m unittest discover -s tests`

Expected: PASS.

- [x] **Step 3: Install and verify the shared core**

Run: `python3 scripts/install_core.py && python3 scripts/install_core.py --check`

Expected: install succeeds and `--check` confirms the runtime matches this checkout.

- [x] **Step 4: Inspect rendered advice**

Run the existing focused hook test or render path and confirm the final instruction requires a completed packet in the native invocation without implying MER itself performs dispatch or captures Main's context.

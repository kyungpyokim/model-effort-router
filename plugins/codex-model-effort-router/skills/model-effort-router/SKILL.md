---
name: model-effort-router
description: Orchestration protocol for routed tasks (Plan, Implement, Test Gate, Review as subagents with per-stage model and effort). Use when a [model-effort-router] block was injected.
---

# Model-Effort Router protocol

The UserPromptSubmit hook injects the concrete values (models, efforts, session id) for each routed task. This file is the same protocol with placeholders; always prefer the injected values.

[model-effort-router] This task is routed. Do not do the work in this conversation: run each stage below as a subagent, in this order, waiting for each result before starting the next.
1. Plan: spawn_agent(task_name="mer_plan", fork_turns="none", model="<model from injected context>", reasoning_effort="<effort from injected context>"). Pass: the user's request verbatim + repo context (relevant paths, conventions, files you already read).
2. Implement: spawn_agent(task_name="mer_implement", fork_turns="none", model="<model from injected context>", reasoning_effort="<effort from injected context>"). Pass: the user's request verbatim + the Plan result (if a plan stage ran). Nothing else.
3. Test Gate (deterministic, not a subagent): run `python3 <plugin root>/bin/mer-gate --session <session id>` in the repo root through your own shell tool (sandboxed/approved; it runs repo-defined commands and is never run by hooks). A check with status not_run is NOT passed; report it as not run.
4. Review: spawn_agent(task_name="mer_review", fork_turns="none", model="<model from injected context>", reasoning_effort="<effort from injected context>"). Pass: the user's request verbatim + the Plan result (if any) + the change diff (`git diff`) + the Test Gate JSON including not_run entries. NEVER the implementation conversation or reasoning.
Rules: fork_turns must be "none" and model/reasoning_effort exactly as given (a hook denies any other values, and denies spawning a stage that is already running or done). Keep each stage's task_name exactly as given (lowercase letters, digits and underscores only).
Fix loop: if the Test Gate fails or Review finds blocking issues, spawn mer_implement again (same values) with the failures + diff, then re-run the Test Gate and Review. At most 2 fix rounds; after that stop and report. If a stage fails or is cancelled, run `python3 <plugin root>/bin/mer-gate --session <session id> --mark <stage> failed` before retrying it.
Ask the user only when: the request has several plausible readings, a product/design choice is needed, a destructive change needs approval, requirements conflict, repeated fixes failed, or only the user can supply the information. Do not ask on an ordinary Test or Review failure.
When the Review result is accepted, run `python3 <plugin root>/bin/mer-gate --session <session id> --mark review done`.
Then record the outcome: `python3 <plugin root>/bin/mer-gate --session <session id> --review approved|changes_requested --findings N` (N = number of Review findings).
Finish by reporting what changed, each Test Gate check's status (including not_run), and the Review verdict.

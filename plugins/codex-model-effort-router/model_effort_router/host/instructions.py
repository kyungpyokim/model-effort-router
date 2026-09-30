"""Orchestration instructions injected on UserPromptSubmit; the same text (with placeholders) is the skill."""

STAGE_INPUT = {
    "plan": "the user's request verbatim + repo context (relevant paths, conventions, files you already read)",
    "implement": "the user's request verbatim + the Plan result (if a plan stage ran). Nothing else",
    "review": "the user's request verbatim + the Plan result (if any) + the change diff (`git diff`) + "
    "the Test Gate JSON including not_run entries. NEVER the implementation conversation or reasoning",
}
TITLES = {"plan": "Plan", "implement": "Implement", "review": "Review"}


def _stage_line(n, stage, model, effort):
    return (f'{n}. {TITLES[stage]}: spawn_agent(task_name="mer-{stage}", fork_turns="none", '
            f'model="{model}", reasoning_effort="{effort}"). Pass: {STAGE_INPUT[stage]}.')


def render(*, order, stages, session_id, gate_cmd, max_fix, level=None, rejected=False):
    """order: stage names (may include test_gate); stages: {name: {"model", "effort"}}."""
    lines = [
        "[model-effort-router] This task is routed. Do not do the work in this conversation: run each "
        "stage below as a subagent, in this order, waiting for each result before starting the next."
        + (f" (difficulty {level})" if level else ""),
    ]
    if rejected:
        lines.append("Note: the /router override line was not understood and was ignored.")
    for n, stage in enumerate(order, 1):
        if stage == "test_gate":
            lines.append(f"{n}. Test Gate (deterministic, not a subagent): run `python3 {gate_cmd} "
                         f"--session {session_id}` in the repo root through your own shell tool (sandboxed/approved; "
                         "it runs repo-defined commands and is never run by hooks). A check with status not_run "
                         "is NOT passed; report it as not run.")
        else:
            st = stages[stage]
            lines.append(_stage_line(n, stage, st["model"], st["effort"]))
    lines.append('Rules: fork_turns must be "none" and model/reasoning_effort exactly as given (a hook denies '
                 "any other values, and denies spawning a stage that is already running or done). "
                 "Keep each stage's task_name exactly as given.")
    if "implement" in order:
        lines.append(f"Fix loop: if the Test Gate fails or Review finds blocking issues, spawn mer-implement again "
                     f"(same values) with the failures + diff, then re-run the Test Gate and Review. At most "
                     f"{max_fix} fix rounds; after that stop and report. If a stage fails or is cancelled, run "
                     f"`python3 {gate_cmd} --session {session_id} --mark <stage> failed` before retrying it.")
    lines.append("Ask the user only when: the request has several plausible readings, a product/design choice is "
                 "needed, a destructive change needs approval, requirements conflict, repeated fixes failed, or "
                 "only the user can supply the information. Do not ask on an ordinary Test or Review failure.")
    if "review" in order:
        lines.append(f"When the Review result is accepted, run `python3 {gate_cmd} --session {session_id} "
                     "--mark review done`.")
    if "review" in order:
        lines.append(f"Then record the outcome: `python3 {gate_cmd} --session {session_id} --review "
                     "approved|changes_requested --findings N` (N = number of Review findings).")
    lines.append("Finish by reporting what changed, each Test Gate check's status (including not_run), and the "
                 "Review verdict.")
    return "\n".join(lines)


def render_from_state(state, *, rejected=False):
    return render(order=state["order"], stages=state["stages"], session_id=state["session_id"],
                  gate_cmd=state["gate_cmd"], max_fix=state["max_fix"], level=state.get("level"),
                  rejected=rejected)


def render_skill():
    placeholder = {"model": "<model from injected context>", "effort": "<effort from injected context>"}
    body = render(order=["plan", "implement", "test_gate", "review"],
                  stages={s: placeholder for s in TITLES}, session_id="<session id>",
                  gate_cmd="<plugin root>/bin/mer-gate", max_fix=2)
    head = ("---\nname: model-effort-router\n"
            "description: Orchestration protocol for routed tasks (Plan, Implement, Test Gate, Review as "
            "subagents with per-stage model and effort). Use when a [model-effort-router] block was injected.\n"
            "---\n\n# Model-Effort Router protocol\n\n"
            "The UserPromptSubmit hook injects the concrete values (models, efforts, session id) for each routed "
            "task. This file is the same protocol with placeholders; always prefer the injected values.\n\n")
    return head + body + "\n"

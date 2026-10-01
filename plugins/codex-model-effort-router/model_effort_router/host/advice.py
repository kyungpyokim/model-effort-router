"""Advisory text for the UserPromptSubmit hook (spec 3.7): what the Router would pick; nothing is enforced."""
from ..adapters.codex import resolve
from ..policy.session import REVIEW_DEFAULT, session_plan


def _setting(profile):
    r = resolve(profile)
    note = f" (requested {r.requested_effort})" if r.requested_effort != r.applied_effort else ""
    return f"{r.model}, reasoning effort {r.applied_effort}{note}"


def render(plan, mer_cmd):
    """Context for a routed prompt. Never mentions subagents; the user decides everything."""
    # the user's own interactive session keeps Codex's subagents: advise as for the "codex" policy
    sp = session_plan(plan.decision, plan.risk_flags, plan.overrides, "codex")
    d = plan.decision
    head = "Difficulty: " + (f"{d.level}" + (f" (confidence {d.confidence:.2f})" if d.confidence is not None else "")
                             if d else "not classified (manual mode)")
    lines = ["[model-effort-router] Advisory only: nothing is enforced and no subagents are needed. "
             "Mention this to the user only if it helps them.", head + f". Risk flags: {', '.join(plan.risk_flags) or 'none'}."]
    if plan.override_rejected:
        lines.append("Note: the /router override line was not understood and was ignored.")
    if plan.target == "plan_only":
        lines.append(f"Recommended for planning: {_setting(sp.plan_profile)}; switch with /model if you want.")
    elif plan.target == "review_only":
        lines.append(f"Recommended for this review: {_setting(sp.review or REVIEW_DEFAULT)}; switch with /model if you want.")
    else:
        lines.append(f"Recommended session: {_setting(sp.start)}; switch with /model if you want.")
        if sp.plan_first:
            lines.append("Plan first: write a short plan before changing code.")
        if sp.review:
            rp = f"{sp.review.tier}:{sp.review.effort}"
            lines.append(f"This work warrants an independent review ({_setting(sp.review)}) after the change. "
                         f"Run it with `{mer_cmd} --review-profile {rp} 'review only: check the current diff for <the task>'`, "
                         f"or run the whole task through `{mer_cmd} '<the task>'` (Test Gate, escalation and review "
                         "included). Single-quote the request (write ' as '\\'') so the shell expands nothing in it.")
    return "\n".join(lines)

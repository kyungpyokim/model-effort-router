"""Advisory text for the UserPromptSubmit hook (spec 3.7): what the Router would pick; nothing is enforced."""
from ..difficulty.decision import format_risk_flags
from ..policy.session import REVIEW_DEFAULT, session_plan
from .hosts import CODEX


def _setting(profile, host):
    r = host.resolve(profile)
    if r.applied_effort is None:  # a model without effort support (claude-haiku-4-5)
        return r.model
    note = f" (requested {r.requested_effort})" if r.requested_effort != r.applied_effort else ""
    return f"{r.model}, {host.effort_word} {r.applied_effort}{note}"


def _already(profile, host, current):
    """The user's default session (model, effort) already is this profile: a model alias like "sonnet" counts
    when it names the same family. Unknown effort never counts as a match."""
    model, effort = current or (None, None)
    model = model.split("[")[0].strip().lower() if model else None  # "sonnet[1m]": a context-size variant, same model
    r = host.resolve(profile)
    family = r.model.split("-")[1] if r.model.count("-") >= 1 else r.model  # claude-sonnet-5-5 -> sonnet
    same_model = bool(model) and model in (r.model, family)
    return same_model and (r.applied_effort is None or effort == r.applied_effort)


def render(plan, mer_cmd, host=CODEX, current=None):
    """Context for a routed prompt, or None when there is nothing to advise (the user's default session, given as
    `current` = (model, effort), already is the recommended one and no plan or review is needed).
    Never mentions subagents; the user decides everything."""
    # the user's own interactive session keeps the host's subagents: advise as for the "codex" policy
    sp = session_plan(plan.decision, plan.risk_flags, plan.overrides, "codex")
    d = plan.decision
    head = "Difficulty: " + (f"{d.level}" + (f" (confidence {d.confidence:.2f})" if d.confidence is not None else "")
                             if d else "not classified (manual mode)")
    lines = ["[model-effort-router] Advisory only: nothing is enforced and no subagents are needed. "
             "Mention this to the user only if it helps them.", head + f". Risk flags: {format_risk_flags(plan.risk_flags)}."]
    if plan.override_rejected:
        lines.append("Note: the /router override line was not understood and was ignored.")
    if plan.target == "plan_only":
        lines.append(f"Recommended for planning: {_setting(sp.plan_profile, host)}; switch with {host.switch_hint} if you want.")
    elif plan.target == "review_only":
        lines.append(f"Recommended for this review: {_setting(sp.review or REVIEW_DEFAULT, host)}; switch with {host.switch_hint} if you want.")
    else:
        if not _already(sp.start, host, current):
            lines.append(f"Recommended session: {_setting(sp.start, host)}; switch with {host.switch_hint} if you want.")
        if sp.plan_first:
            lines.append("Plan first: write a short plan before changing code.")
        if sp.review:
            rp = f"{sp.review.tier}:{sp.review.effort}"
            lines.append(f"This work warrants an independent review ({_setting(sp.review, host)}) after the change. "
                         f"Run it with `{mer_cmd} --review-profile {rp} 'review only: check the current diff for <the task>'`, "
                         f"or run the whole task through `{mer_cmd} '<the task>'` (Test Gate, escalation and review "
                         "included). Single-quote the request (write ' as '\\'') so the shell expands nothing in it.")
    return "\n".join(lines) if len(lines) > 2 else None

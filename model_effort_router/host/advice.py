"""Main-agent guidance; hooks do not mutate the active model or create Subagents."""

import re

from ..policy.targeting import NO_ROUTE

_CLAUDE_ALIAS = re.compile(
    r"^(?:claude-)?(sonnet|opus|haiku|fable)(?:-|$)"
)  # the Agent call's model parameter takes aliases only


def effort_pair(model, effort):
    """The one display form for a routed model and effort, shared by every host surface."""
    return f"{model} · effort {effort}"


def _claude_invocation(plan):
    alias = _CLAUDE_ALIAS.match(plan.model or "")
    if not alias:
        return (
            f"invoke: {plan.model} has no Agent model alias, so handle the task directly or use a project agent "
            "in .claude/agents/ with `model:` set. "
        )
    if alias[1] == "haiku":  # no supported efforts (adapters/claude.py), so no effort agent applies
        return 'invoke: Agent(model="haiku"); effort does not apply to haiku. '
    pinned = (
        ""
        if plan.model == alias[1]
        else (f" (`{alias[1]}` runs Claude Code's current {alias[1]} model, which may differ from {plan.model})")
    )
    return (
        f'invoke: Agent(subagent_type="model-effort-router:effort-{plan.applied_effort}", model="{alias[1]}"){pinned}. '
    )


def render(plan, mer_cmd, host):
    decision = plan.decision
    if not decision or plan.target == NO_ROUTE:
        return None
    is_review = decision.role == "review"
    packet = (
        "goal, decisions, constraints, actual diff, verification status/results"
        if is_review
        else "task, context, decisions, constraints, relevant_files, expected_result"
    )
    handoff = (
        "Use facts from the current request and relevant conversation to populate the packet, label unknowns, and include the completed packet directly in the host-native Subagent invocation. "
        "Do not forward the full conversation or private reasoning. "
    )
    if is_review:
        handoff += "Mark checks that were not run as not run. Ask the review Subagent to inspect the diff, fix actionable findings, run relevant verification, and report changes and unresolved issues. "
    alternatives = tuple(model for model in plan.model_options if model != plan.model)
    other = (
        f" Other configured options: {', '.join(alternatives)} (user-selectable, not automatic fallbacks)."
        if alternatives
        else ""
    )
    invocation = _claude_invocation(plan) if host.name == "claude" else ""
    return (
        f"[model-effort-router] {decision.role} → {plan.agent} · {effort_pair(plan.model, plan.applied_effort)}. "
        "Main: route this single task to a native Subagent using the host's supported "
        f"model/effort controls, or handle it directly when Main's model/effort already match or project instructions require it. "
        f"{invocation}Build a compact Context Packet with {packet}. {handoff}"
        "Integrate the result, then decide whether another worker is needed. The hook provides advice only; it does not inspect Main's conversation or invoke the Subagent, and does not change this Main turn's model/settings."
        + other
    )

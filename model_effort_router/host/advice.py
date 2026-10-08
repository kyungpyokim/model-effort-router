"""Main-agent guidance; hooks do not mutate the active model or create Subagents."""

import re

from ..policy.targeting import NO_ROUTE
from .main_model import normalize

NO_ROUTE_MESSAGE = "[model-effort-router] No route selected; continue in the main agent."
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


def matches(plan, main_model):
    """True/False when Main's model equals/differs from the routed one; None when Main's model is unknown."""
    main = normalize(main_model)
    return None if main is None else main == normalize(plan.model)


def _codex_invocation(plan):
    return (
        f'invoke: spawn_agent(model="{plan.model}", reasoning_effort="{plan.applied_effort}", '
        'fork_turns="none", message=<Context Packet>). This router advice asks for the model/reasoning_effort '
        "to be set. "
    )


def _header(plan, decision):
    return f"[model-effort-router] {decision.role} → {plan.agent} · {effort_pair(plan.model, plan.applied_effort)}."


def render(plan, mer_cmd, host, main_model=None):
    if plan.target == NO_ROUTE:
        return NO_ROUTE_MESSAGE if plan.mode == "auto" else None
    decision = plan.decision
    if not decision:
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
    same = matches(plan, main_model)
    if same is False and host.name == "claude" and not _CLAUDE_ALIAS.match(plan.model or ""):
        same = None  # no Agent alias to spawn with, so a flat "spawn" order would contradict the invocation
    if same:
        return (
            f"{_header(plan, decision)} Main already runs {normalize(main_model)}; no Subagent needed. "
            f"Proceed directly in Main (Main cannot change its own effort; routed effort is {plan.applied_effort})."
        )
    if same is False:
        invocation = _claude_invocation(plan) if host.name == "claude" else _codex_invocation(plan)
        return (
            f"{_header(plan, decision)} Main model {normalize(main_model)} ≠ routed {plan.model}: spawn the Subagent. "
            f"{invocation}Build a compact Context Packet with {packet}. {handoff}"
            "Integrate the result, then decide whether another worker is needed. "
            "Handle it in Main only if the user explicitly told Main to do it this turn; otherwise, if you skip "
            "routing, add one line `skipped routing: <reason>` to your response. "
            "The hook provides advice only; it does not invoke the Subagent or change this Main turn's model/settings."
            + other
        )
    return (
        f"{_header(plan, decision)} "
        "Main: route this single task to a native Subagent using the host's supported "
        f"model/effort controls, or handle it directly when Main's model/effort already match or project instructions require it. "
        f"{invocation}Build a compact Context Packet with {packet}. {handoff}"
        "Integrate the result, then decide whether another worker is needed. The hook provides advice only; it does not inspect Main's conversation or invoke the Subagent, and does not change this Main turn's model/settings."
        + other
    )

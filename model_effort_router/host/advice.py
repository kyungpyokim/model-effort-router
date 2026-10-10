"""Main-agent guidance; hooks do not mutate the active model or create Subagents."""

import re
from types import SimpleNamespace

from ..policy.targeting import NO_ROUTE
from .main_model import normalize

NO_ROUTE_MESSAGE = "[model-effort-router] No route selected; continue in the main agent."
_CLAUDE_ALIAS = re.compile(
    r"^(?:claude-)?(sonnet|opus|haiku|fable)(?:-|$)"
)  # the Agent call's model parameter takes aliases only


_CLAUDE, _CODEX = SimpleNamespace(name="claude"), SimpleNamespace(name="codex")


def effort_pair(model, effort):
    """The one display form for a routed model and effort, shared by every host surface."""
    return f"{model} · effort {effort}"


def _invocation_args(plan, host):
    """The one description of the call Main is told to make; the advice text and the log both build from it.
    None when no call applies (a Claude model without an Agent alias)."""
    if host.name != "claude":
        return {"model": plan.model, "reasoning_effort": plan.applied_effort}
    alias = _CLAUDE_ALIAS.match(plan.model or "")
    if not alias:
        return None
    # haiku has no supported efforts (adapters/claude.py), so no effort agent applies
    agent = None if alias[1] == "haiku" else f"model-effort-router:effort-{plan.applied_effort}"
    return {"subagent_type": agent, "model": alias[1]}


def _claude_invocation(plan):
    args = _invocation_args(plan, _CLAUDE)
    if args is None:
        return (
            f"invoke: {plan.model} has no Agent model alias, so handle the task directly or use a project agent "
            "in .claude/agents/ with `model:` set. "
        )
    if args["subagent_type"] is None:
        return f'invoke: Agent(model="{args["model"]}"); effort does not apply to haiku. '
    pinned = (
        ""
        if plan.model == args["model"]
        else (
            f" (`{args['model']}` runs Claude Code's current {args['model']} model, which may differ from {plan.model})"
        )
    )
    return f'invoke: Agent(subagent_type="{args["subagent_type"]}", model="{args["model"]}"){pinned}. '


def matches(plan, main_model):
    """True/False when Main's model equals/differs from the routed one; None when Main's model is unknown."""
    main = normalize(main_model)
    return None if main is None else main == normalize(plan.model)


def _same_model(plan, host, main_model):
    """True/False/None as `matches`, but None when Claude has no Agent alias to spawn with (a flat spawn order would contradict the invocation)."""
    same = matches(plan, main_model)
    if same is False and host.name == "claude" and not _CLAUDE_ALIAS.match(plan.model or ""):
        return None
    return same


def summary(plan, host, main_model=None):
    """What `render` told Main, as data: the log and the text derive from the same values and cannot disagree."""
    if plan.target == NO_ROUTE:
        return {"action": "no_route"}  # the mode is logged separately
    if not plan.decision:
        return {"action": "off"}
    same = _same_model(plan, host, main_model)
    action = "inline_same_model" if same else "spawn" if same is False else "advise"
    spawns = action != "inline_same_model" and (action == "spawn" or host.name == "claude")
    return {
        "action": action,
        "main_model": normalize(main_model),
        "routed_model": plan.model,
        "routed_effort": plan.applied_effort,
        "agent": plan.agent,
        "invocation": _invocation_args(plan, host) if spawns else None,
    }


def _codex_invocation(plan):
    args = _invocation_args(plan, _CODEX)
    return (
        f'invoke: spawn_agent(model="{args["model"]}", reasoning_effort="{args["reasoning_effort"]}", '
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
    same = _same_model(plan, host, main_model)
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

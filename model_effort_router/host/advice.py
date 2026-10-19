"""Main-agent guidance; hooks do not mutate the active model or create Subagents."""

import re
from types import SimpleNamespace

from ..policy.targeting import NO_ROUTE
from .main_model import normalize

NO_ROUTE_MESSAGE = "[model-effort-router] No route selected; continue in the main agent."
_CLAUDE_ALIAS = re.compile(
    r"^(?:claude-)?(sonnet|opus|haiku|fable)(?:-|$)"
)  # the Agent call's model parameter takes aliases only


def _split_cause(cause):
    name, _, detail = cause.partition(":")
    if detail.startswith("HTTP "):
        detail = detail.split(" [", 1)[0]
    return name, detail


def fallback_line(plan):
    """One user-visible line saying why the classifier fell back; "" when it did not."""
    if not plan.classifier_causes:
        return ""
    failed = ", ".join(f"{n} failed ({d})" for n, d in map(_split_cause, plan.classifier_causes))
    by = "no_route" if plan.target == NO_ROUTE else f"classified by {plan.decision.backend}"
    return f"[model-effort-router] classifier fallback: {failed} → {by}"


def failure_line(causes):
    """One user-visible line for a routing turn where every classifier failed."""
    failed = ", ".join(f"{n} ({d})" for n, d in map(_split_cause, causes)) or "none configured"
    return f"[model-effort-router] classifier failed: {failed}; no routing advice this turn."


def tell_user(line):
    """Suffix for additionalContext (after any reply-tag instruction): the Codex and Claude desktop apps show no systemMessage."""
    return f"Required: tell the user in one line that the router classifier had a problem: {line} "


_CLAUDE, _CODEX = SimpleNamespace(name="claude"), SimpleNamespace(name="codex")


def effort_pair(model, effort):
    """The one display form for a routed model and effort, shared by every host surface."""
    return f"{model} · effort {effort}"


def _main_tag(main_model, main_effort, placeholder):
    """`[main: …]` body: Main's model (or the placeholder it fills in) plus its effort when the host reported one."""
    model = normalize(main_model) or placeholder
    return effort_pair(model, main_effort) if main_effort else model


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
    if host.name == "antigravity":
        return None
    same = matches(plan, main_model)
    if same is False and host.name == "claude" and not _CLAUDE_ALIAS.match(plan.model or ""):
        return None
    return same


def _independent_review(plan, host):
    return (
        plan.decision.role == "review" and host.name in ("codex", "claude") and _invocation_args(plan, host) is not None
    )


def summary(plan, host, main_model=None):
    """What `render` told Main, as data: the log and the text derive from the same values and cannot disagree."""
    if plan.target == NO_ROUTE:
        return {"action": "no_route"}  # the mode is logged separately
    if not plan.decision:
        return {"action": "off"}
    same = _same_model(plan, host, main_model)
    action = "spawn" if same is False or _independent_review(plan, host) else "inline_same_model" if same else "advise"
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
        "to be set. Do not pass agent_type: a role's config (.codex/agents/*.toml) overrides model and "
        "reasoning_effort. "
    )


_APPS = {
    "codex": "the Codex app",
    "claude": "the Claude desktop app",
    "antigravity": "the Antigravity app",
}
_FIRST_LINE = "before any tool call, start your first message of this turn with"


def _reply_tag(plan, host, main_model, main_effort, spawns):
    """The apps show no hook output, so Main names the model in the first line it writes this turn, before any tool call."""
    app = _APPS.get(host.name)
    if app is None:
        return ""
    main = f"`[main: {_main_tag(main_model, main_effort, '<your model id>')}]`"  # unknown Main model: Main fills in its own id
    if not spawns:
        return f"Required: {_FIRST_LINE} the line {main} ({app} does not show hook messages). "
    return (
        f"Required: {_FIRST_LINE} one line naming the model that will do the work: "
        f"`[routed: {effort_pair(plan.model, plan.applied_effort)}]` if you spawn the Subagent, or {main} "
        f"if you handle it in Main ({app} does not show hook messages). "
    )


def _header(plan, decision):
    return f"[model-effort-router] {decision.role} → {plan.agent} · {effort_pair(plan.model, plan.applied_effort)}."


def render(plan, mer_cmd, host, main_model=None, main_effort=None):
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
    separate_review = _independent_review(plan, host)
    if same and not separate_review:
        return (
            f"{_header(plan, decision)} {_reply_tag(plan, host, main_model, main_effort, spawns=False)}"
            f"Main already runs {normalize(main_model)}; no Subagent needed. "
            f"Proceed directly in Main (Main cannot change its own effort; routed effort is {plan.applied_effort})."
        )
    if same is False or separate_review:
        invocation = _claude_invocation(plan) if host.name == "claude" else _codex_invocation(plan)
        reason = (
            "Use a separate Subagent for independent review. "
            if separate_review
            else f"Main model {normalize(main_model)} ≠ routed {plan.model}: spawn the Subagent. "
        )
        return (
            f"{_header(plan, decision)} {_reply_tag(plan, host, main_model, main_effort, spawns=True)}"
            f"{reason}"
            f"{invocation}Build a compact Context Packet with {packet}. {handoff}"
            "Integrate the result, then decide whether another worker is needed. "
            "Handle it in Main only if the user explicitly told Main to do it this turn; otherwise, if you skip "
            "routing, add one line `skipped routing: <reason>` to your response. "
            "The hook provides advice only; it does not invoke the Subagent or change this Main turn's model/settings."
            + other
        )
    return (
        f"{_header(plan, decision)} {_reply_tag(plan, host, main_model, main_effort, spawns=_invocation_args(plan, host) is not None)}"
        "Main: route this single task to a native Subagent using the host's supported "
        f"model/effort controls, or handle it directly when Main's model/effort already match or project instructions require it. "
        f"{invocation}Build a compact Context Packet with {packet}. {handoff}"
        "Integrate the result, then decide whether another worker is needed. The hook provides advice only; it does not inspect Main's conversation or invoke the Subagent, and does not change this Main turn's model/settings."
        + other
    )


# --- experimental router.mode=policy (A/B vs auto): no classifier, Main reads the lane table and decides ---


def is_policy(plan):
    """A policy-mode plan that Main decides; an explicit role/effort override carries a decision and renders normally."""
    return plan.mode == "policy" and plan.decision is None and plan.target != NO_ROUTE


def is_haiku(model):
    alias = _CLAUDE_ALIAS.match(model or "")
    return bool(alias) and alias[1] == "haiku"


def policy_lanes(lanes):
    return {lane: lanes[lane]["primary"] for lane in ("execution", "reasoning")}


def policy_summary(lanes, main_model=None):
    return {"action": "policy", "main_model": normalize(main_model), "lanes": policy_lanes(lanes)}


def policy_notice(lanes):
    models = policy_lanes(lanes)
    return f"[model-effort-router] policy · execution → {models['execution']} · reasoning → {models['reasoning']}"


def render_policy(lanes, host, main_model=None, main_effort=None):
    rows, calls = [], []
    for lane, roles in (
        ("execution", "implementation, fix, lint, test"),
        ("reasoning", "plan, design, review, analysis"),
    ):
        model, efforts = lanes[lane]["primary"], "/".join(lanes[lane]["efforts"])
        rows.append(f"{lane} ({roles}) → {model} [efforts: {efforts}]")
        stub = SimpleNamespace(model=model, applied_effort="<effort>")
        calls.append(f"{lane}: " + (_claude_invocation(stub) if host.name == "claude" else _codex_invocation(stub)))
    tag = (
        f"Required: {_FIRST_LINE} one line naming the model that will do the work: "
        "`[routed: <lane model> · effort <effort>]` if you spawn the Subagent, or "
        f"`[main: {_main_tag(main_model, main_effort, '<your model>')}]` if you handle it in Main ({_APPS[host.name]} does not show hook messages). "
        if host.name in _APPS
        else ""
    )
    main = f" ({normalize(main_model)})" if normalize(main_model) else ""
    return (
        f"[model-effort-router] policy: {tag}Pick the lane for this task: {'; '.join(rows)}. "
        "Pick an effort that lane supports. "
        f"If the lane's model is Main's model{main}, or the task is trivial (a quick lookup or status check), "
        f"handle it in Main. Otherwise spawn a Subagent. {''.join(calls)}"
        "Build a compact Context Packet with task, context, decisions, constraints, relevant_files, expected_result. "
        "The hook provides advice only; it does not invoke the Subagent or change this Main turn's model/settings."
    )

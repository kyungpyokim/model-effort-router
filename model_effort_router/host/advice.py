"""Model and effort recommendations for host hooks."""

import re

from ..policy.targeting import NO_ROUTE
from .main_model import normalize

NO_ROUTE_MESSAGE = "[model-effort-router] No route selected; continue in the main agent."
# Hosts whose app window renders no hook output; Main has to show the recommendation itself.
_DESKTOP_APPS = {"codex": "the Codex app", "claude": "the Claude desktop app"}


def _split_cause(cause):
    name, _, detail = cause.partition(":")
    if detail.startswith("HTTP "):
        detail = detail.split(" [", 1)[0]
    return name, detail


def fallback_line(plan):
    """One user-visible line saying why the classifier fell back; empty when it did not."""
    if not plan.classifier_causes:
        return ""
    failed = ", ".join(f"{name} failed ({detail})" for name, detail in map(_split_cause, plan.classifier_causes))
    by = "no_route" if plan.target == NO_ROUTE else f"classified by {plan.decision.backend}"
    return f"[model-effort-router] classifier fallback: {failed} → {by}"


def failure_line(causes):
    """One user-visible line for a routing turn where every classifier failed."""
    failed = ", ".join(f"{name} ({detail})" for name, detail in map(_split_cause, causes)) or "none configured"
    return f"[model-effort-router] classifier failed: {failed}; no routing advice this turn."


def tell_user(line):
    """Suffix for additionalContext when the host hides hook messages."""
    return f"Required: tell the user in one line that the router classifier had a problem: {line} "


def effort_pair(model, effort):
    """The shared display form for a recommended model and effort."""
    return f"{model} · effort {effort}"


def matches(plan, main_model):
    """True/False when Main's model equals/differs from the recommendation; None when it is unknown."""
    main = normalize(main_model)
    return None if main is None else main == normalize(plan.model)


def _same_model(plan, host, main_model):
    """True/False/None; Antigravity does not expose a stable model identifier."""
    return None if host.name == "antigravity" else matches(plan, main_model)


def summary(plan, host, main_model=None):
    """The selected model/effort recommendation as log data."""
    if plan.target == NO_ROUTE:
        return {"action": "no_route"}
    if not plan.decision:
        return {"action": "off"}
    return {
        "action": "already_selected" if _same_model(plan, host, main_model) else "recommend",
        "selection_only": True,
        "main_model": normalize(main_model),
        "routed_model": plan.model,
        "routed_effort": plan.applied_effort,
        "agent": plan.agent,
    }


def _header(plan, decision):
    return f"[model-effort-router] {decision.role} → {plan.agent} · {effort_pair(plan.model, plan.applied_effort)}."


def reply_tag(plan, host):
    """The desktop apps render no hook output, so Main repeats the recommendation as its first line."""
    app = _DESKTOP_APPS.get(host.name)
    if app is None or plan.target == NO_ROUTE or not plan.decision:
        return ""
    line = _header(plan, plan.decision).rstrip(".")
    return (
        "Required: before any tool call, start your first message of this turn with the line "
        f"`{line}` ({app} does not show hook messages). "
    )


def render(plan, host, main_model=None):
    if plan.target == NO_ROUTE:
        return NO_ROUTE_MESSAGE if plan.mode == "auto" else None
    decision = plan.decision
    if not decision:
        return None
    alternatives = tuple(model for model in plan.model_options if model != plan.model)
    other = f" Other configured options: {', '.join(alternatives)} (user-selectable)." if alternatives else ""
    tag = reply_tag(plan, host)
    if _same_model(plan, host, main_model):
        return (
            f"{tag}{_header(plan, decision)} Main already uses {normalize(main_model)}. "
            f"Recommended effort: {plan.applied_effort}. MER recommends model settings only; it does not change them."
        )
    return (
        f"{tag}{_header(plan, decision)} Recommended model: {plan.model}; effort: {plan.applied_effort}. "
        "MER recommends model settings only; it does not change them." + other
    )


def is_policy(plan):
    """A policy-mode plan that uses the configured role lanes without classification."""
    return plan.mode == "policy" and plan.decision is None and plan.target != NO_ROUTE


def policy_lanes(lanes):
    return {lane: lanes[lane]["primary"] for lane in ("execution", "reasoning")}


def policy_summary(lanes, main_model=None):
    return {
        "action": "policy",
        "selection_only": True,
        "main_model": normalize(main_model),
        "lanes": policy_lanes(lanes),
    }


def policy_notice(lanes):
    models = policy_lanes(lanes)
    return f"[model-effort-router] policy · execution → {models['execution']} · reasoning → {models['reasoning']}"


def is_haiku(model):
    """Recognize old logged Claude advice that used effort-specific agents."""
    return bool(re.match(r"^(?:claude-)?haiku(?:-|$)", model or ""))


def render_policy(lanes):
    rows = []
    for lane, roles in (
        ("execution", "implementation, fix, lint, test"),
        ("reasoning", "plan, design, review, analysis"),
    ):
        model, efforts = lanes[lane]["primary"], "/".join(lanes[lane]["efforts"])
        rows.append(f"{lane} ({roles}) → {model} [efforts: {efforts}]")
    return (
        f"[model-effort-router] policy: configured model lanes: {'; '.join(rows)}. "
        "Choose a lane's model and supported effort for the request. "
        "MER recommends model settings only; it does not change them."
    )

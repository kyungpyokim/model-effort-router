"""Role/effort classification and host model mapping."""

from dataclasses import dataclass
from typing import Optional

from ..difficulty.chain import ClassificationError, classify_with_fallback
from ..difficulty.decision import (
    EFFORTS,
    EXECUTION_ROLES,
    DifficultyDecision,
    DifficultyInput,
    merge_risk_flags,
)
from ..difficulty.registry import BACKENDS, create
from ..difficulty.risk import detect_risk_flags
from ..difficulty.usage import sum_usage
from .config import resolve_config
from .overrides import parse_override
from .targeting import NO_ROUTE, ROUTE, classify_target


@dataclass(frozen=True)
class RoutePlan:
    target: str
    mode: str
    decision: Optional[DifficultyDecision] = None
    risk_flags: tuple = ()
    model: Optional[str] = None
    fallback_model: Optional[str] = None
    agent: Optional[str] = None
    requested_effort: Optional[str] = None
    applied_effort: Optional[str] = None
    classifier_usage: Optional[dict] = None
    classifier_usage_missing: bool = False
    override_rejected: bool = False
    fallback_reason: Optional[str] = None
    model_options: tuple = ()


class _Broken:
    def __init__(self, name, error):
        self.name, self.error = name, error
        self.calls_model = False

    def classify(self, task, timeout_s):
        raise self.error


def _make_backends(config, registry, user_config=None):
    out = []
    for name in (config.backend, config.fallback):
        if name == "none":
            continue
        try:
            backend_options = getattr(config, name, None) if name in ("nimble", "laya") else None
            options = {"options": backend_options} if backend_options else {}
            if name == "jev" and user_config:
                options["api_key"] = user_config.get("jev", {}).get("api_key")
            if name == "openai_decisions" and user_config:
                options["api_key"] = user_config.get("openai", {}).get("api_key")
            out.append(create(name, registry, **options))
        except Exception as exc:
            out.append(_Broken(name, exc))
    return out


def _usage(backends, selected):
    attempted = []
    for backend in backends:
        attempted.append(backend)
        if getattr(backend, "name", None) == selected:
            break
    model_calls = [b for b in attempted if getattr(b, "calls_model", False)]
    reported = [
        b.last_usage
        for b in model_calls
        if isinstance(getattr(b, "last_usage", None), dict)
    ]
    return (sum_usage(reported) if reported else None, len(reported) < len(model_calls))


def route(
    message,
    *,
    paths=(),
    repo_config=None,
    user_config=None,
    registry=None,
    host="codex",
    explicit=False,
    role_override=None,
    effort_override=None,
    context="",
    repo_summary="",
):
    registry = BACKENDS if registry is None else registry
    override, text = parse_override(message)
    if override.rejected:
        return RoutePlan(NO_ROUTE, "invalid_override", override_rejected=True)
    cfg = resolve_config(
        task=override.as_config(), repo=repo_config, user=user_config, registry=registry
    )
    flags = detect_risk_flags(text, paths)
    role_override = role_override if role_override is not None else override.role
    effort_override = (
        effort_override if effort_override is not None else override.effort
    )
    phase_override = role_override is not None or effort_override is not None
    if phase_override and (role_override is None or effort_override is None):
        raise ValueError("--role and --effort must be provided together")
    if cfg.mode == "off":
        return RoutePlan(NO_ROUTE, "off")
    if cfg.mode == "manual" and not phase_override:
        return RoutePlan(NO_ROUTE, "manual")
    backends = _make_backends(cfg, registry, user_config)
    task = DifficultyInput(text, tuple(paths), repo_summary=repo_summary, context=context)
    if phase_override:
        decision = DifficultyDecision(role_override, effort_override, "explicit")
    elif explicit:
        decision, _causes = classify_with_fallback(task, backends, cfg.timeout_s)
    else:
        decision, rest, asked = None, backends, False
        # Only the first (primary) slot may decide eligibility; target answers from fallback-slot backends are ignored (the regex decides).
        if backends and getattr(backends[0], "provides_target", False):
            asked = True  # ask it ALONE first
            try:
                decision, _causes = classify_with_fallback(task, backends[:1], cfg.timeout_s)
            except ClassificationError:  # failed: the regex gates the fallback, so chit-chat never pays for it
                rest = backends[1:]
        target = decision.target if decision else None
        if target is None:
            target = classify_target(text, paths)
        if target == NO_ROUTE:  # keep what the target backend spent (and its decision) for the log
            usage, missing = _usage(backends[:1], backends[0].name) if asked else (None, False)
            return RoutePlan(NO_ROUTE, cfg.mode, decision, classifier_usage=usage, classifier_usage_missing=missing)
        if decision is None:
            decision, _causes = classify_with_fallback(task, rest, cfg.timeout_s)
    flags = merge_risk_flags(flags)
    effort = decision.effort
    safety_floor = (
        decision.role == "review"
        and bool(set(flags) & {"security", "data_loss", "data_migration"})
        or decision.role == "design"
        and bool(set(flags) & {"security", "auth"})
    )
    if safety_floor and EFFORTS.index(effort) < EFFORTS.index("high"):
        effort = "high"
    lane = "execution" if decision.role in EXECUTION_ROLES else "reasoning"
    try:
        mapped = cfg.models[host][lane]
    except KeyError as exc:
        raise ValueError(
            f"no model mapping configured for host {host!r} and lane {lane!r}"
        ) from exc
    if effort not in mapped["efforts"]:
        raise ValueError(
            f"{host} {lane} model {mapped['primary']} does not support requested effort {effort}; configure a capable primary"
        )
    if host == "antigravity":
        from ..adapters.antigravity import resolve_model

        primary = resolve_model(mapped["primary"], effort, mapped["efforts"]).model
        fallback = (
            resolve_model(mapped["fallback"], effort, mapped["efforts"]).model
            if mapped["fallback"]
            else None
        )
        alternatives = tuple(
            resolve_model(model, effort, mapped["efforts"]).model
            for model in mapped.get("alternatives", [])
        )
    else:
        primary, fallback = mapped["primary"], mapped["fallback"]
        alternatives = tuple(mapped.get("alternatives", []))
    usage, missing = (
        _usage(backends, decision.backend)
        if decision.backend != "explicit"
        else (None, False)
    )
    return RoutePlan(
        ROUTE,
        cfg.mode,
        decision,
        flags,
        primary,
        fallback,
        lane,
        decision.effort,
        effort,
        usage,
        missing,
        False,
        None,
        (primary, *alternatives),
    )

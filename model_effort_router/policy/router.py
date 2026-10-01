"""Compose: override/config -> targeting -> backend chain -> risk merge -> Stage Policy -> RoutePlan."""
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Optional, Tuple

from ..difficulty.chain import classify_with_fallback
from ..difficulty.decision import DifficultyDecision, DifficultyInput
from ..difficulty.registry import BACKENDS, create
from ..difficulty.risk import detect_risk_flags
from ..difficulty.usage import sum_usage
from .config import resolve_config
from .overrides import parse_override
from .stages import StagePolicyResult, decide_manual, decide_stages, restrict_to_target
from .targeting import NO_ROUTE, ROUTE, classify_target


@dataclass(frozen=True)
class RoutePlan:
    target: str
    mode: str
    decision: Optional[DifficultyDecision] = None
    policy: Optional[StagePolicyResult] = None
    risk_flags: Tuple[str, ...] = ()
    override_rejected: bool = False  # user typed a /router line that did not parse
    classifier_usage: Optional[dict] = None  # summed token counts of model-calling backends that reported
    classifier_usage_missing: bool = False  # a model-calling backend ran but reported nothing
    overrides: Mapping = field(default_factory=lambda: MappingProxyType({}))  # {"session": Profile} when typed


class _Broken:
    """Stands in for a backend whose factory failed, so the chain records the cause."""

    def __init__(self, name, exc):
        self.name, self._exc = name, exc

    def classify(self, task, timeout_s):
        raise self._exc


def _backends(config, registry):
    names = [config.backend] + ([config.fallback] if config.fallback != "none" else [])
    out = []
    for name in names:
        try:
            out.append(create(name, registry))
        except Exception as exc:
            out.append(_Broken(name, exc))
    return out


def _classifier_usage(backends, decision):
    """(summed usage or None, missing?). Only backends that call a model (`calls_model`) and actually ran count;
    "ran" = up to the backend that produced the decision (all of them if the chain fell to the default)."""
    ran = []
    for b in backends:
        ran.append(b)
        if getattr(b, "name", None) == decision.backend:
            break
    model = [b for b in ran if getattr(b, "calls_model", False)]
    reported = [u for u in (getattr(b, "last_usage", None) for b in model) if isinstance(u, dict)]
    return (sum_usage(reported) if reported else None), len(reported) < len(model)


def route(message, *, paths=(), repo_config=None, user_config=None, registry=None, promotion=None, explicit=False):
    """`explicit`: the user invoked the `mer` CLI themselves, so a non-dev message is still routed."""
    registry = BACKENDS if registry is None else registry
    override, text = parse_override(message)
    rejected = override.rejected
    config = resolve_config(
        task=override.as_config(), repo=repo_config, user=user_config, registry=registry
    )
    flags = detect_risk_flags(text, paths)  # always runs (spec 7)
    typed = {"session": override.session} if override.session else {}

    if config.mode == "off":
        return RoutePlan(NO_ROUTE, "off", override_rejected=rejected)

    if config.mode == "manual":  # no classification; only what the user typed
        if not (override.stages or typed):
            return RoutePlan(NO_ROUTE, "manual", override_rejected=rejected)
        return RoutePlan(
            ROUTE, "manual", None, decide_manual(override.stages, flags), flags, rejected, overrides=typed
        )

    # Typed stage overrides turn an ambiguous/no_route message into a route, but keep plan_only/review_only.
    target = classify_target(text, paths)
    if target == NO_ROUTE and (override.stages or explicit):
        target = ROUTE
    if target == NO_ROUTE:
        return RoutePlan(NO_ROUTE, "auto", override_rejected=rejected)

    backends = _backends(config, registry)
    decision = classify_with_fallback(
        DifficultyInput(task=text, paths=tuple(paths)), backends, config.timeout_s
    )
    decision = decision.with_risk_flags(flags)
    policy = decide_stages(decision, promotion=promotion, overrides=override.stages)
    usage, usage_missing = _classifier_usage(backends, decision)
    return RoutePlan(
        target, "auto", decision, restrict_to_target(policy, target), decision.risk_flags, rejected,
        usage, usage_missing, typed,
    )

"""Compose: override/config -> targeting -> backend chain -> risk merge -> Stage Policy -> RoutePlan."""
from dataclasses import dataclass
from typing import Optional, Tuple

from ..difficulty.chain import classify_with_fallback
from ..difficulty.decision import DifficultyDecision, DifficultyInput
from ..difficulty.registry import BACKENDS, create
from ..difficulty.risk import detect_risk_flags
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


def route(message, *, paths=(), repo_config=None, user_config=None, registry=None, promotion=None):
    registry = BACKENDS if registry is None else registry
    override, text = parse_override(message)
    rejected = override.rejected
    config = resolve_config(
        task=override.as_config(), repo=repo_config, user=user_config, registry=registry
    )
    flags = detect_risk_flags(text, paths)  # always runs (spec 7)

    if config.mode == "off":
        return RoutePlan(NO_ROUTE, "off", override_rejected=rejected)

    if config.mode == "manual":  # no classification; only what the user typed
        if not override.stages:
            return RoutePlan(NO_ROUTE, "manual", override_rejected=rejected)
        return RoutePlan(
            ROUTE, "manual", None, decide_manual(override.stages, flags), flags, rejected
        )

    # Typed stage overrides turn an ambiguous/no_route message into a route, but keep plan_only/review_only.
    target = classify_target(text, paths)
    if target == NO_ROUTE and override.stages:
        target = ROUTE
    if target == NO_ROUTE:
        return RoutePlan(NO_ROUTE, "auto", override_rejected=rejected)

    decision = classify_with_fallback(
        DifficultyInput(task=text, paths=tuple(paths)), _backends(config, registry), config.timeout_s
    )
    decision = decision.with_risk_flags(flags)
    policy = decide_stages(decision, promotion=promotion, overrides=override.stages)
    return RoutePlan(
        target, "auto", decision, restrict_to_target(policy, target), decision.risk_flags, rejected
    )

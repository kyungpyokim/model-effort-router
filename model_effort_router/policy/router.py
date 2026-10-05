"""Compose: override/config -> targeting -> backend chain -> risk merge -> RoutePlan (session_plan turns it into a profile)."""
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Mapping, Optional, Tuple

from ..difficulty.chain import classify_with_fallback, default_decision
from ..difficulty.decision import DifficultyDecision, DifficultyInput
from ..difficulty.registry import BACKENDS, create
from ..difficulty.risk import detect_risk_flags
from ..difficulty.usage import sum_usage
from ..difficulty.conditional import NimbleJevBackend
from ..difficulty.nimble import NimbleBackend
from .config import resolve_config
from .overrides import parse_override
from .targeting import NO_ROUTE, ROUTE, classify_target

NIMBLE_OPTION_BACKENDS = {"nimble": NimbleBackend, "nimble_jev": NimbleJevBackend}  # who receives `difficulty.nimble`


@dataclass(frozen=True)
class RoutePlan:
    target: str
    mode: str
    decision: Optional[DifficultyDecision] = None
    risk_flags: Tuple[str, ...] = ()
    override_rejected: bool = False  # user typed a /router line that did not parse
    classifier_usage: Optional[dict] = None  # summed token counts of model-calling backends that reported
    classifier_usage_missing: bool = False  # a model-calling backend ran but reported nothing
    overrides: Mapping = field(default_factory=lambda: MappingProxyType({}))  # {"session": Profile} when typed
    target_source: str = "rules"  # who decided `target`: "backend" (provides_target), "rules" or "override"


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
            # nimble's options go only to the real NimbleBackend / NimbleJevBackend: any other factory (a stand-in, a test double) gets none
            real = name in NIMBLE_OPTION_BACKENDS and config.nimble and registry.get(name) is NIMBLE_OPTION_BACKENDS[name]
            out.append(create(name, registry, **({"options": config.nimble} if real else {})))
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


def route(message, *, paths=(), repo_config=None, user_config=None, registry=None, explicit=False):
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
        if not typed:
            return RoutePlan(NO_ROUTE, "manual", override_rejected=rejected)
        return RoutePlan(ROUTE, "manual", None, risk_flags=flags, override_rejected=rejected, overrides=typed)

    backends = _backends(config, registry)
    task = DifficultyInput(task=text, paths=tuple(paths))
    decision, target, source, rest, causes = None, None, "rules", backends, ()
    if getattr(backends[0], "provides_target", False):  # the backend decides the target: ask it ALONE first (3.3)
        first = classify_with_fallback(task, backends[:1], config.timeout_s)
        if first.backend == getattr(backends[0], "name", None) and first.target:
            decision, target, source = first, first.target, "backend"
        else:  # it failed: the rules gate the fallback again, so chit-chat never pays for a fallback call
            rest, causes = backends[1:], first.reason_codes
    if target is None:
        target = classify_target(text, paths)
    # A typed session override or an explicit mer call turns no_route into a route, but keeps plan_only/review_only.
    if target == NO_ROUTE and (typed or explicit):
        target, source = ROUTE, ("override" if source == "backend" else source)
    if target == NO_ROUTE and decision is None:
        return RoutePlan(NO_ROUTE, "auto", override_rejected=rejected)

    if decision is None:
        decision = classify_with_fallback(task, rest, config.timeout_s) if rest else default_decision(causes)
        if causes:  # keep the failed primary visible in the log, also when the fallback fails too
            codes = (tuple(causes) + decision.reason_codes if decision.backend == "default"
                     else decision.reason_codes + tuple(f"fallback_cause:{c}" for c in causes))
            decision = replace(decision, reason_codes=codes)
    decision = decision.with_risk_flags(flags)
    usage, usage_missing = _classifier_usage(backends, decision)
    return RoutePlan(
        target, "auto", decision, risk_flags=decision.risk_flags, override_rejected=rejected,
        classifier_usage=usage, classifier_usage_missing=usage_missing, overrides=typed, target_source=source,
    )

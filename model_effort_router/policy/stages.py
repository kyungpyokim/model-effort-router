"""Stage Policy (spec 11): level default -> risk minimums -> (opt-in) promotion -> user override."""
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Optional, Tuple

from ..difficulty.decision import LEVELS, RISK_FLAGS, DifficultyDecision
from ..profiles.profiles import STAGES, Profile

E, B, F = "economy", "balanced", "frontier"

# 11.1 -- initial values, tuned only by evaluation results. (plan, implement, review); plan None = skipped.
LEVEL_DEFAULTS = {
    "L1": (None, Profile(E, "medium"), Profile(E, "medium")),
    "L2": (None, Profile(E, "medium"), Profile(F, "high")),
    "L3": (Profile(F, "high"), Profile(B, "high"), Profile(F, "high")),
    "L4": (Profile(F, "high"), Profile(F, "high"), Profile(F, "high")),
    "L5": (Profile(F, "xhigh"), Profile(F, "high"), Profile(F, "xhigh")),
}

# 11.2 -- minimum profiles. A present "plan" minimum also forces the plan stage to run.
RISK_MINIMUMS = {
    "security": {"plan": Profile(F, "high"), "review": Profile(F, "high")},
    "auth": {"plan": Profile(F, "high"), "review": Profile(F, "high")},
    "payment": {"plan": Profile(F, "high"), "review": Profile(F, "high")},
    "data_migration": {"plan": Profile(F, "high"), "review": Profile(F, "xhigh")},
    "data_loss": {"plan": Profile(F, "high"), "review": Profile(F, "xhigh")},
    "concurrency": {"review": Profile(F, "high")},
}
assert set(RISK_MINIMUMS) == set(RISK_FLAGS)

PLAN_WHEN_REQUESTED = Profile(F, "high")  # plan_only on a level that normally skips Plan


@dataclass(frozen=True)
class PromotionConfig:
    """Confidence promotion (11.2). Off until thresholds are calibrated per backend."""

    enabled: bool = False
    thresholds: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class StageProfile:
    stage: str
    tier: Optional[str] = None
    effort: Optional[str] = None


@dataclass(frozen=True)
class StagePolicyResult:
    level: Optional[str]  # None for manual mode (nothing was classified)
    stages: Tuple[StageProfile, ...]
    applied_rules: Tuple[str, ...]

    def to_dict(self) -> dict:
        def stage(s):
            d = {"stage": s.stage}
            if s.tier:
                d.update(tier=s.tier, effort=s.effort)
            return d

        return {
            "level": self.level,
            "stages": [stage(s) for s in self.stages],
            "applied_rules": list(self.applied_rules),
        }


def _promoted_level(decision: DifficultyDecision, promotion: Optional[PromotionConfig]) -> str:
    if not promotion or not promotion.enabled or decision.confidence is None:
        return decision.level
    threshold = promotion.thresholds.get(decision.backend)
    if threshold is None or decision.confidence >= threshold:
        return decision.level
    return LEVELS[min(LEVELS.index(decision.level) + 1, len(LEVELS) - 1)]


def _assemble(level, profiles, rules) -> StagePolicyResult:
    """Stages in STAGES order, test_gate right after implement."""
    stages = []
    for stage in STAGES:
        profile = profiles.get(stage)
        if profile:
            stages.append(StageProfile(stage, profile.tier, profile.effort))
        if stage == "implement" and profile:
            stages.append(StageProfile("test_gate"))
    return StagePolicyResult(level, tuple(stages), tuple(rules))


def _risk_floors(risk_flags) -> dict:
    floors = {}
    for flag in (f for f in RISK_FLAGS if f in risk_flags):
        for stage, floor in RISK_MINIMUMS[flag].items():
            floors[stage] = floors[stage].at_least(floor) if stage in floors else floor
    return floors


def _apply_overrides(profiles, rules, overrides, floors):
    """Overrides beat level defaults but are re-clamped to risk minimums (never lowered)."""
    for stage, profile in (overrides or {}).items():
        rules.append(f"override:{stage}")
        floor = floors.get(stage)
        clamped = profile.at_least(floor) if floor else profile
        if clamped != profile:
            rules.append(f"override_clamped:{stage}")
        profiles[stage] = clamped


def decide_stages(decision, *, promotion=None, overrides=None) -> StagePolicyResult:
    level = _promoted_level(decision, promotion)
    plan, implement, review = LEVEL_DEFAULTS[level]
    profiles = {"plan": plan, "implement": implement, "review": review}
    rules = ["level_default"]

    floors = _risk_floors(decision.risk_flags)
    for flag in (f for f in RISK_FLAGS if f in decision.risk_flags):
        rules.append(f"risk_min:{flag}")
    for stage, floor in floors.items():
        current = profiles[stage]
        profiles[stage] = current.at_least(floor) if current else floor  # never lowers

    if level != decision.level:
        rules.append(f"confidence_promotion:{decision.level}->{level}")

    _apply_overrides(profiles, rules, overrides, floors)
    return _assemble(level, profiles, rules)


def decide_manual(overrides, risk_flags) -> StagePolicyResult:
    """Manual mode: the user's stages plus any stage a risk minimum requires, all clamped (spec 7, 11.2)."""
    floors = _risk_floors(risk_flags)
    profiles = dict(floors)  # stages a risk flag requires run even if the user did not name them
    rules = [f"risk_min:{f}" for f in RISK_FLAGS if f in risk_flags]
    _apply_overrides(profiles, rules, overrides, floors)
    return _assemble(None, profiles, rules)


def restrict_to_target(result: StagePolicyResult, target: str) -> StagePolicyResult:
    """plan_only / review_only keep just that stage; route is unchanged."""
    if target not in ("plan_only", "review_only"):
        return result
    stage = target.split("_")[0]
    kept = [s for s in result.stages if s.stage == stage]
    if not kept:  # plan requested explicitly although this level skips Plan
        kept = [StageProfile("plan", PLAN_WHEN_REQUESTED.tier, PLAN_WHEN_REQUESTED.effort)]
    return StagePolicyResult(result.level, tuple(kept), result.applied_rules + (f"target:{target}",))

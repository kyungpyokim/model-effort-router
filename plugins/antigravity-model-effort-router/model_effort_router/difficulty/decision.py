"""DifficultyInput / DifficultyDecision (spec 6, 7)."""
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Mapping, Optional, Tuple

LEVELS = ("L1", "L2", "L3", "L4", "L5")
RISK_FLAGS = ("security", "auth", "payment", "data_migration", "data_loss", "concurrency")
TARGETS = ("route", "plan_only", "review_only", "no_route")  # same values as policy.targeting (no import: cycle)
DISTRIBUTION_TOLERANCE = 0.05


def merge_risk_flags(*groups):
    """Union of flag groups, in canonical order."""
    merged = set().union(*groups)
    return tuple(f for f in RISK_FLAGS if f in merged)


def format_risk_flags(flags):
    return ", ".join(flags) or "none"


@dataclass(frozen=True)
class DifficultyInput:
    task: str
    paths: Tuple[str, ...] = ()
    repo_summary: str = ""


@dataclass(frozen=True)
class DifficultyDecision:
    level: str
    backend: str
    confidence: Optional[float] = None
    distribution: Optional[Mapping[str, float]] = None
    reason_codes: Tuple[str, ...] = ()
    risk_flags: Tuple[str, ...] = ()
    target: Optional[str] = None  # set only by backends that also decide the routing target (provides_target)

    def __post_init__(self):
        if self.level not in LEVELS:
            raise ValueError(f"level must be one of {LEVELS}, got {self.level!r}")
        if not self.backend or not isinstance(self.backend, str):
            raise ValueError("backend is required")
        if self.confidence is not None and not (
            isinstance(self.confidence, (int, float))
            and not isinstance(self.confidence, bool)
            and 0.0 <= self.confidence <= 1.0
        ):
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence!r}")
        if self.target is not None and self.target not in TARGETS:
            raise ValueError(f"target must be None or one of {TARGETS}, got {self.target!r}")
        unknown = set(self.risk_flags) - set(RISK_FLAGS)
        if unknown:
            raise ValueError(f"unknown risk flags: {sorted(unknown)}")
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(self, "risk_flags", tuple(self.risk_flags))
        if self.distribution is not None:
            dist = dict(self.distribution)
            if set(dist) - set(LEVELS) or any(not 0.0 <= v <= 1.0 for v in dist.values()):
                raise ValueError("distribution needs L1..L5 keys with values in [0, 1]")
            if abs(sum(dist.values()) - 1.0) > DISTRIBUTION_TOLERANCE:
                raise ValueError("distribution must sum to ~1")
            object.__setattr__(self, "distribution", MappingProxyType(dist))

    def with_risk_flags(self, extra) -> "DifficultyDecision":
        return replace(self, risk_flags=merge_risk_flags(self.risk_flags, extra))

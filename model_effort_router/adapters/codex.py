"""Codex host adapter: abstract profile -> model + effort. Everything model-specific is data."""
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Tuple

from ..profiles.profiles import EFFORTS, TIERS, Profile
from .common import EFFORT_ORDER, ResolvedProfile, apply_support as _apply_support

_LUNA = ("low", "medium", "high", "xhigh", "max")
# Per-model supported efforts from the phase-0 spike (models_cache.json).
_MODEL_EFFORTS = MappingProxyType(
    {"gpt-6-luna": _LUNA, "gpt-6-sol": _LUNA + ("ultra",), "gpt-6.1-sol": _LUNA + ("ultra",)}
)
# Default tier models -- to confirm at install time (spec 12).
_TIERS = MappingProxyType({"economy": "gpt-6-luna", "balanced": "gpt-6-luna", "frontier": "gpt-6.1-sol"})
_EFFORTS = MappingProxyType({"medium": "medium", "high": "high", "xhigh": "xhigh"})


@dataclass(frozen=True)
class CodexConfig:
    tiers: Mapping[str, str] = field(default_factory=lambda: _TIERS)
    efforts: Mapping[str, str] = field(default_factory=lambda: _EFFORTS)
    model_efforts: Mapping[str, Tuple[str, ...]] = field(default_factory=lambda: _MODEL_EFFORTS)

    def __post_init__(self):
        if set(self.tiers) != set(TIERS):
            raise ValueError(f"tiers must define exactly {TIERS}")
        if set(self.efforts) != set(EFFORTS):
            raise ValueError(f"efforts must define exactly {EFFORTS}")
        for abstract, host in self.efforts.items():
            if host not in EFFORT_ORDER:
                raise ValueError(f"efforts[{abstract!r}]={host!r} is not one of {EFFORT_ORDER}")
        for model, supported in self.model_efforts.items():
            if not isinstance(supported, (tuple, list)) or not supported:
                raise ValueError(f"model {model!r}: supported efforts must be a non-empty list")
            unknown = [e for e in supported if e not in EFFORT_ORDER]
            if unknown:
                raise ValueError(f"model {model!r}: unknown efforts {unknown}")
        for tier, model in self.tiers.items():
            if model not in self.model_efforts:
                raise ValueError(f"tier {tier!r} uses model {model!r} with no supported-effort data")


def resolve(profile: Profile, config: CodexConfig = CodexConfig()) -> ResolvedProfile:
    model = config.tiers[profile.tier]
    requested = config.efforts[profile.effort]
    return ResolvedProfile(profile.tier, model, requested, _apply_support(requested, config.model_efforts[model]))

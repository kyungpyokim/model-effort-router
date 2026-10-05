"""Antigravity profiles: effort is part of the model slug (agy 1.2.16)."""

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Tuple

from ..profiles.profiles import EFFORTS, TIERS, Profile
from .common import ResolvedProfile, apply_support

ANTIGRAVITY_EFFORTS = ("medium", "high")
_TIERS = MappingProxyType(
    {
        "economy": "gemini-3.8-flash",
        "balanced": "claude-sonnet-5-5",
        "frontier": "claude-opus-5-5",
    }
)
_EFFORTS = MappingProxyType({"medium": "medium", "high": "high", "xhigh": "high"})
_MODEL_EFFORTS = MappingProxyType(dict.fromkeys(_TIERS.values(), ANTIGRAVITY_EFFORTS))


@dataclass(frozen=True)
class AntigravityConfig:
    tiers: Mapping[str, str] = field(default_factory=lambda: _TIERS)
    efforts: Mapping[str, str] = field(default_factory=lambda: _EFFORTS)
    model_efforts: Mapping[str, Tuple[str, ...]] = field(
        default_factory=lambda: _MODEL_EFFORTS
    )

    def __post_init__(self):
        if not all(
            isinstance(value, Mapping)
            for value in (self.tiers, self.efforts, self.model_efforts)
        ):
            raise ValueError("tiers, efforts and model_efforts must be mappings")
        if set(self.tiers) != set(TIERS):
            raise ValueError(f"tiers must define exactly {TIERS}")
        if set(self.efforts) != set(EFFORTS):
            raise ValueError(f"efforts must define exactly {EFFORTS}")
        for effort in self.efforts.values():
            if effort not in ANTIGRAVITY_EFFORTS:
                raise ValueError(f"unsupported Antigravity effort: {effort!r}")
        for model, supported in self.model_efforts.items():
            if (
                not isinstance(model, str)
                or not model
                or model.startswith("-")
                or any(c.isspace() for c in model)
            ):
                raise ValueError("model must be a nonempty model slug")
            if not isinstance(supported, (tuple, list)) or not supported:
                raise ValueError(
                    f"model {model!r}: supported efforts must be a nonempty list"
                )
            if any(e not in ANTIGRAVITY_EFFORTS for e in supported):
                raise ValueError(f"model {model!r}: unknown supported effort")
        for tier, model in self.tiers.items():
            if not isinstance(model, str) or model not in self.model_efforts:
                raise ValueError(f"tier {tier!r} has no supported-effort data")
        object.__setattr__(self, "tiers", MappingProxyType(dict(self.tiers)))
        object.__setattr__(self, "efforts", MappingProxyType(dict(self.efforts)))
        object.__setattr__(
            self,
            "model_efforts",
            MappingProxyType({k: tuple(v) for k, v in self.model_efforts.items()}),
        )


def resolve(
    profile: Profile, config: AntigravityConfig = AntigravityConfig()
) -> ResolvedProfile:
    model = config.tiers[profile.tier]
    applied = apply_support(config.efforts[profile.effort], config.model_efforts[model])
    return ResolvedProfile(profile.tier, f"{model}-{applied}", profile.effort, applied)

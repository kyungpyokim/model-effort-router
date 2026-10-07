"""Abstract profiles: model tier + reasoning effort (spec 12). Both ordered low -> high."""
from dataclasses import dataclass

from ..difficulty.efforts import PROFILE_EFFORTS as EFFORTS

TIERS = ("economy", "balanced", "frontier")


@dataclass(frozen=True)
class Profile:
    tier: str
    effort: str

    def __post_init__(self):
        if self.tier not in TIERS:
            raise ValueError(f"unknown tier: {self.tier!r}")
        if self.effort not in EFFORTS:
            raise ValueError(f"unknown effort: {self.effort!r}")

    def at_least(self, floor: "Profile") -> "Profile":
        """Element-wise max; never lowers either axis."""
        return Profile(
            max(self.tier, floor.tier, key=TIERS.index),
            max(self.effort, floor.effort, key=EFFORTS.index),
        )


def parse_profile(text) -> Profile:
    """'frontier:high' -> Profile. Raises ValueError on anything else."""
    parts = text.split(":") if isinstance(text, str) else []
    if len(parts) != 2:
        raise ValueError(f"profile must look like 'tier:effort', got {text!r}")
    return Profile(*parts)

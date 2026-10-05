"""Profile results and effort fallback shared by host adapters."""
from dataclasses import dataclass
from typing import Optional

EFFORT_ORDER = ("low", "medium", "high", "xhigh", "max", "ultra")


@dataclass(frozen=True)
class ResolvedProfile:
    tier: str
    model: str
    requested_effort: str
    applied_effort: Optional[str]  # None when the model takes no effort flag


def apply_support(requested: str, supported) -> str:
    """Nearest higher supported effort, else the highest supported one."""
    ranked = sorted(supported, key=EFFORT_ORDER.index)
    want = EFFORT_ORDER.index(requested)
    return next((e for e in ranked if EFFORT_ORDER.index(e) >= want), ranked[-1])

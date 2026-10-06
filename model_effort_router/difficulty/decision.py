"""Classifier output contract and independently detected safety flags."""
from dataclasses import dataclass
from math import isfinite
from typing import Optional, Tuple

ROLES = ("implementation", "fix", "lint", "test", "plan", "design", "review", "analysis")
EFFORTS = ("low", "medium", "high", "xhigh")
EXECUTION_ROLES = frozenset(("implementation", "fix", "lint", "test"))
RISK_FLAGS = ("security", "auth", "payment", "data_migration", "data_loss", "concurrency")


def merge_risk_flags(*groups):
    return tuple(flag for flag in RISK_FLAGS if any(flag in group for group in groups))


@dataclass(frozen=True)
class DifficultyInput:
    task: str
    paths: Tuple[str, ...] = ()
    repo_summary: str = ""


@dataclass(frozen=True)
class DifficultyDecision:
    role: str
    effort: str
    backend: str
    confidence: Optional[float] = None
    reason_code: Optional[str] = None

    def __post_init__(self):
        if self.role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}, got {self.role!r}")
        if self.effort not in EFFORTS:
            raise ValueError(f"effort must be one of {EFFORTS}, got {self.effort!r}")
        if not isinstance(self.backend, str) or not self.backend:
            raise ValueError("backend is required")
        if self.confidence is not None and (
            isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float))
            or not isfinite(self.confidence) or not 0 <= self.confidence <= 1
        ):
            raise ValueError(f"confidence must be finite and in [0, 1], got {self.confidence!r}")
        if self.reason_code is not None and not isinstance(self.reason_code, str):
            raise ValueError("reason_code must be a string")

"""Data models for benchmark evaluation corpus."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    task: str
    task_type: str
    facts: dict[str, str]
    expected_level: str
    expected_tier: str = "standard"
    expected_risk_flags: tuple[str, ...] = ()
    expected_unresolved: tuple[str, ...] = ()

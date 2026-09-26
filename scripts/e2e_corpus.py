"""Frozen Execution Corpus manifest loading and validation.

The Execution Corpus v1 manifest is frozen before any live model call for the
E2E token/cost benchmark. This module only reads committed stdlib JSON; it
never invokes a model or classifier.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

CORPUS_RELATIVE_DIR = Path("evals") / "execution_corpus"
FIXTURES_RELATIVE_DIR = CORPUS_RELATIVE_DIR / "fixtures"
ALLOWED_TASK_TYPES = frozenset({"implementation", "local_refactoring", "architectural_refactoring"})
ALLOWED_TIERS = frozenset({"standard", "elevated", "critical"})
LEVELS = ("L1", "L2", "L3", "L4", "L5")
EXPECTED_CASES = 15
EXPECTED_PER_LEVEL = 3


@dataclass(frozen=True)
class ExecutionCase:
    """One frozen execution-corpus case with its gold metadata."""

    name: str
    task_type: str
    level: str
    tier: str
    task: str
    fixture_dir: Path
    test_cmd: str
    acceptance: str


def load_execution_cases(path: Path) -> tuple[ExecutionCase, ...]:
    """Read the frozen JSON manifest into immutable execution cases."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = tuple(
        ExecutionCase(
            name=entry["name"],
            task_type=entry["task_type"],
            level=entry["level"],
            tier=entry["tier"],
            task=entry["task"],
            fixture_dir=Path(entry["fixture_dir"]),
            test_cmd=entry["test_cmd"],
            acceptance=entry["acceptance"],
        )
        for entry in payload["cases"]
    )
    return cases


def validate_execution_corpus(cases: Sequence[ExecutionCase], repo_root: Path) -> None:
    """Raise ValueError when the frozen corpus violates the v1 contract."""
    errors: list[str] = []

    names = [case.name for case in cases]
    if len(cases) != EXPECTED_CASES:
        errors.append(f"expected {EXPECTED_CASES} cases, got {len(cases)}")
    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    if duplicates:
        errors.append(f"duplicate case IDs: {duplicates}")

    level_counts = Counter(case.level for case in cases)
    expected_counts = Counter({level: EXPECTED_PER_LEVEL for level in LEVELS})
    if level_counts != expected_counts:
        errors.append(f"level counts must be {dict(expected_counts)}, got {dict(level_counts)}")

    if not any(case.level == "L5" and case.tier == "elevated" for case in cases):
        errors.append("at least one L5 case must be on the elevated/security tier")

    fixtures_root = (repo_root / FIXTURES_RELATIVE_DIR).resolve()
    for case in cases:
        if case.task_type not in ALLOWED_TASK_TYPES:
            errors.append(f"{case.name}: task_type {case.task_type!r} not in approved set")
        if case.tier not in ALLOWED_TIERS:
            errors.append(f"{case.name}: tier {case.tier!r} not supported by the router")
        if case.level not in LEVELS:
            errors.append(f"{case.name}: level {case.level!r} not in L1-L5")
        if case.fixture_dir.is_absolute() or not (repo_root / case.fixture_dir).resolve().is_relative_to(fixtures_root):
            errors.append(f"{case.name}: fixture_dir {case.fixture_dir} escapes {FIXTURES_RELATIVE_DIR}")
        if not case.test_cmd.strip():
            errors.append(f"{case.name}: test_cmd must be non-empty")
        if not case.acceptance.strip():
            errors.append(f"{case.name}: acceptance must be non-empty")

    if errors:
        raise ValueError("execution corpus invalid: " + "; ".join(errors))

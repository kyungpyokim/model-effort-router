"""Shared-parser check: quote-stripping must live in one place, not three."""
from __future__ import annotations

import ast
from pathlib import Path

FIXTURE_ROOT = Path(__file__).resolve().parents[1]
QUOTE = chr(34)


def quote_stripping_counts() -> dict[str, int]:
    """Bare double-quote literals per fixture source file, only where present."""
    counts: dict[str, int] = {}
    for path in sorted(FIXTURE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and node.value == QUOTE
        )
        if found:
            counts[str(path.relative_to(FIXTURE_ROOT))] = found
    return counts


def test_quote_stripping_is_defined_in_exactly_one_place() -> None:
    counts = quote_stripping_counts()

    assert sum(counts.values()) == 1, (
        "the duplicated string-parsing helper must be refactored into one "
        f"shared parser; quote-stripping literals found in: {counts}"
    )

"""Behavior checks: query-string parsing must stay green through the refactor."""
from __future__ import annotations


def _split_pair(text: str, sep: str) -> tuple[str, str]:
    """Split one key/value pair and drop surrounding quotes from the value."""
    key, _, value = text.partition(sep)
    return key.strip(), value.strip().strip('"')


def parse_query(query: str) -> dict[str, str]:
    """Parse a query string of ``a=1&b="two"`` pairs, dropping quotes."""
    return dict(_split_pair(part, "=") for part in query.split("&"))


def test_parses_simple_pairs() -> None:
    assert parse_query("a=1&b=2") == {"a": "1", "b": "2"}


def test_strips_spaces_and_quotes() -> None:
    assert parse_query('name = "Ada"') == {"name": "Ada"}

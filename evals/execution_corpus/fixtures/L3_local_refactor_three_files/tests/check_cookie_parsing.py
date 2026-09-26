"""Behavior checks: cookie parsing must stay green through the refactor."""
from __future__ import annotations


def _split_pair(text: str, sep: str) -> tuple[str, str]:
    """Split one key/value pair and drop surrounding quotes from the value."""
    key, _, value = text.partition(sep)
    return key.strip(), value.strip().strip('"')


def parse_cookie(header: str) -> dict[str, str]:
    """Parse ``a="1"; b=2`` cookie pairs, dropping quotes from values."""
    return dict(_split_pair(part.strip(), "=") for part in header.split(";"))


def test_parses_cookie_pairs() -> None:
    assert parse_cookie('session="abc123"; theme="dark"') == {
        "session": "abc123",
        "theme": "dark",
    }


def test_parses_a_single_pair() -> None:
    assert parse_cookie("count=3") == {"count": "3"}

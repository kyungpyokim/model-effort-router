"""Behavior checks: header-line parsing must stay green through the refactor."""
from __future__ import annotations


def _split_pair(text: str, sep: str) -> tuple[str, str]:
    """Split one key/value pair and drop surrounding quotes from the value."""
    key, _, value = text.partition(sep)
    return key.strip(), value.strip().strip('"')


def parse_headers(block: str) -> dict[str, str]:
    """Parse ``Name: value`` lines, dropping quotes from values."""
    return dict(_split_pair(line, ":") for line in block.splitlines() if line)


def test_parses_header_lines() -> None:
    block = "X-Trace: abc123\nAccept: text/plain"
    assert parse_headers(block) == {"X-Trace": "abc123", "Accept": "text/plain"}


def test_strips_spaces_and_quotes() -> None:
    block = 'Content-Type: "application/json"'
    assert parse_headers(block) == {"Content-Type": "application/json"}

"""Acceptance checks: pagination boundary behavior."""
import view


def test_exact_multiple_needs_no_extra_page() -> None:
    assert view.total_pages(10, 5) == 2


def test_remainder_needs_an_extra_page() -> None:
    assert view.total_pages(11, 5) == 3


def test_single_partial_page() -> None:
    assert view.total_pages(1, 5) == 1


def test_empty_list_needs_no_page() -> None:
    assert view.total_pages(0, 5) == 0

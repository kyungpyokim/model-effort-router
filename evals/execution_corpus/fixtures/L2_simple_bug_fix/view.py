"""Pagination math for a list view."""


def total_pages(total_items: int, per_page: int) -> int:
    """Return how many pages are needed to show every item."""
    return total_items // per_page

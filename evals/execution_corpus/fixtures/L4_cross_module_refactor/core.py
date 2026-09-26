"""Core helpers shared across the application (billing helpers live here too)."""
from __future__ import annotations


def slugify(text: str) -> str:
    """Lower-case and hyphenate a title."""
    return "-".join(text.lower().split())


def apply_tax(amount: float, rate: float) -> float:
    """Return amount plus tax at rate, rounded to cents."""
    return round(amount * (1 + rate), 2)


def format_invoice_total(invoice: dict) -> str:
    """Render an invoice total as a currency string."""
    return f"{invoice['currency']} {invoice['total']:.2f}"

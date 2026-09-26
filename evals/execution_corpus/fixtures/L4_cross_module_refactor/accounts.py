"""Account statements: tax-inclusive balances rendered as totals."""
from __future__ import annotations

from core import apply_tax, format_invoice_total


def statement_total(account: dict) -> str:
    """Render the account balance including tax."""
    total = apply_tax(account["balance"], account["tax_rate"])
    invoice = {"total": total, "currency": account.get("currency", "USD")}
    return format_invoice_total(invoice)

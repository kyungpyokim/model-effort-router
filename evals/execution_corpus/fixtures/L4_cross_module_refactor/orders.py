"""Order placement: charge a subtotal and render its invoice."""
from __future__ import annotations

from core import apply_tax, format_invoice_total


def invoice_for(order: dict) -> str:
    """Charge an order and render its invoice total."""
    total = apply_tax(order["subtotal"], order["tax_rate"])
    invoice = {"total": total, "currency": order.get("currency", "USD")}
    return format_invoice_total(invoice)

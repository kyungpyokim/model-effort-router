"""Behavior checks: billing math must stay green across the refactor."""
from __future__ import annotations

import accounts
import core
import orders


def test_apply_tax_math_via_the_order_callsite() -> None:
    assert orders.apply_tax(100.0, 0.08) == 108.0


def test_apply_tax_rounds_to_cents_via_the_account_callsite() -> None:
    assert accounts.apply_tax(99.99, 0.075) == 107.49


def test_format_invoice_total_renders_currency() -> None:
    assert orders.format_invoice_total({"total": 12.5, "currency": "USD"}) == "USD 12.50"


def test_invoice_for_charges_the_order() -> None:
    order = {"subtotal": 100.0, "tax_rate": 0.05}
    assert orders.invoice_for(order) == "USD 105.00"


def test_statement_total_renders_the_balance() -> None:
    account = {"balance": 200.0, "tax_rate": 0.1}
    assert accounts.statement_total(account) == "USD 220.00"


def test_core_keeps_its_own_non_billing_utility() -> None:
    assert core.slugify("Hello World") == "hello-world"

from .models import Item


def line_total(item: Item, qty: int) -> int:
    if qty <= 0:
        raise ValueError("quantity must be positive")
    return item.price_cents * qty


def order_total(items: dict, lines: list) -> int:
    return sum(line_total(items[sku], qty) for sku, qty in lines)

from .models import Order
from .pricing import order_total


def place_order(items: dict, order: Order) -> int:
    """Checks stock, decrements it and returns the total in cents."""
    for sku, qty in order.lines:
        if sku not in items:
            raise KeyError(f"unknown sku: {sku}")
        if items[sku].stock < qty:
            raise ValueError(f"insufficient stock for {sku}")
    total = order_total(items, order.lines)
    for sku, qty in order.lines:
        items[sku].stock -= qty
    return total

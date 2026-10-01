from dataclasses import dataclass, field


@dataclass
class Item:
    sku: str
    name: str
    price_cents: int
    stock: int = 0


@dataclass
class Order:
    lines: list = field(default_factory=list)  # [(sku, qty)]

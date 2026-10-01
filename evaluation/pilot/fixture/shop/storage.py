import json

from .models import Item


def save_items(path, items):
    with open(path, "w", encoding="utf-8") as f:
        json.dump([vars(i) for i in items.values()], f)


def load_items(path):
    with open(path, encoding="utf-8") as f:
        return {d["sku"]: Item(**d) for d in json.load(f)}

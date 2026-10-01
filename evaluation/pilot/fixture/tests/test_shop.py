import os
import tempfile
import unittest

from shop import auth
from shop.models import Item, Order
from shop.orders import place_order
from shop.pricing import line_total, order_total
from shop.storage import load_items, save_items


def items():
    return {"a": Item("a", "Apple", 100, 5), "b": Item("b", "Bread", 250, 2)}


class ShopTest(unittest.TestCase):
    def test_line_total_and_validation(self):
        self.assertEqual(line_total(items()["a"], 3), 300)
        with self.assertRaises(ValueError):
            line_total(items()["a"], 0)

    def test_order_total_and_stock(self):
        inv = items()
        self.assertEqual(order_total(inv, [("a", 2), ("b", 1)]), 450)
        self.assertEqual(place_order(inv, Order([("a", 2)])), 200)
        self.assertEqual(inv["a"].stock, 3)

    def test_order_errors(self):
        with self.assertRaises(KeyError):
            place_order(items(), Order([("z", 1)]))
        with self.assertRaises(ValueError):
            place_order(items(), Order([("b", 3)]))

    def test_storage_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "items.json")
            save_items(path, items())
            self.assertEqual(load_items(path), items())

    def test_token(self):
        self.assertEqual(auth.verify_token(auth.make_token("ann")), "ann")
        with self.assertRaises(PermissionError):
            auth.verify_token("ann.deadbeef")


if __name__ == "__main__":
    unittest.main()

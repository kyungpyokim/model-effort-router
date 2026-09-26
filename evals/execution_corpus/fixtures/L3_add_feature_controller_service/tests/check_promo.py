"""Acceptance checks: promo validation across promo_service and cart_controller."""
import pytest

import cart_controller
import promo_service


def test_validate_promo_normalizes_the_code() -> None:
    assert promo_service.validate_promo("  save10 ") == "SAVE10"


def test_validate_promo_requires_a_value() -> None:
    with pytest.raises(ValueError):
        promo_service.validate_promo("   ")


def test_validate_promo_rejects_punctuation() -> None:
    with pytest.raises(ValueError):
        promo_service.validate_promo("SAVE-10")


def test_validate_promo_rejects_unknown_codes() -> None:
    with pytest.raises(ValueError):
        promo_service.validate_promo("FREEBIE")


def test_discount_for_an_active_code() -> None:
    assert promo_service.discount_for("SAVE10") == 10


def test_discount_for_an_unknown_code() -> None:
    assert promo_service.discount_for("NOPE") == 0


def test_apply_promo_normalizes_and_discounts() -> None:
    cart = {"total": 100}
    assert cart_controller.apply_promo(cart, " save10 ") == {
        "total": 100,
        "discount": 10,
        "promo_code": "SAVE10",
    }


def test_apply_promo_applies_each_active_discount() -> None:
    cart = {"total": 100}
    assert cart_controller.apply_promo(cart, "welcome20")["discount"] == 20


def test_apply_promo_rejects_an_invalid_code() -> None:
    cart = {"total": 100}
    with pytest.raises(ValueError):
        cart_controller.apply_promo(cart, "nope")
    assert cart == {"total": 100}


def test_apply_promo_rejects_an_unknown_code() -> None:
    cart = {"total": 100}
    with pytest.raises(ValueError):
        cart_controller.apply_promo(cart, "FREEBIE")


def test_apply_promo_returns_a_new_cart() -> None:
    cart = {"total": 100}
    updated = cart_controller.apply_promo(cart, "SAVE10")
    assert updated is not cart
    assert cart == {"total": 100}

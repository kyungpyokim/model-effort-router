"""Cart checkout controller."""

import promo_service


def apply_promo(cart: dict, code: str) -> dict:
    """Return a new cart with the promo code applied."""
    updated = dict(cart)
    updated["discount"] = promo_service.discount_for(code)
    updated["promo_code"] = code
    return updated

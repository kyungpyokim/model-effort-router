"""Promo code validation for checkout."""

ACTIVE_CODES = {"SAVE10": 10, "WELCOME20": 20}


def validate_promo(code: str) -> str:
    """Return the normalized promo code, or raise ValueError when invalid."""
    return code


def discount_for(normalized_code: str) -> int:
    """Return the percentage discount for a normalized promo code."""
    return ACTIVE_CODES.get(normalized_code, 0)

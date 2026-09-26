"""Payload validation for users and orders."""


def validate_user(payload: dict) -> list[str]:
    """Return validation errors for a user payload."""
    errors: list[str] = []
    code = str(payload.get("code", "")).strip()
    if not code:
        errors.append("code is required")
    elif not code.isalnum():
        errors.append("code must be alphanumeric")
    return errors


def validate_order(payload: dict) -> list[str]:
    """Return validation errors for an order payload."""
    errors: list[str] = []
    code = str(payload.get("code", "")).strip()
    if not code:
        errors.append("code is required")
    elif not code.isalnum():
        errors.append("code must be alphanumeric")
    if int(payload.get("quantity", 0)) < 1:
        errors.append("quantity must be positive")
    return errors

"""Acceptance checks: unchanged behavior plus a duplication check."""
import ast
from pathlib import Path

import validator

SOURCE = Path(__file__).resolve().parents[1] / "validator.py"
CODE_MESSAGES = ("code is required", "code must be alphanumeric")


def test_validate_user_accepts_a_good_code() -> None:
    assert validator.validate_user({"code": "AB12"}) == []


def test_validate_user_requires_a_code() -> None:
    assert validator.validate_user({}) == ["code is required"]


def test_validate_user_rejects_punctuation() -> None:
    assert validator.validate_user({"code": "a b"}) == ["code must be alphanumeric"]


def test_validate_order_accepts_a_positive_quantity() -> None:
    assert validator.validate_order({"code": "AB12", "quantity": 2}) == []


def test_validate_order_requires_a_positive_quantity() -> None:
    assert validator.validate_order({"code": "AB12"}) == ["quantity must be positive"]


def test_code_validation_messages_are_defined_once() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    duplicated = {message: literals.count(message) for message in CODE_MESSAGES}
    still_duplicated = {message: count for message, count in duplicated.items() if count != 1}

    assert still_duplicated == {}, (
        "duplicated validation logic must be extracted into one shared local "
        f"function; message literals found more than once: {still_duplicated}"
    )

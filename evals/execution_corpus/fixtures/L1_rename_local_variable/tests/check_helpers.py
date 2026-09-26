"""Acceptance checks: unchanged behavior plus the local rename."""
import ast
from pathlib import Path

import helpers

SOURCE = Path(__file__).resolve().parents[1] / "helpers.py"


def test_helper_keeps_its_behavior() -> None:
    assert helpers.helper(3) == 7


def test_helper_keeps_zero_behavior() -> None:
    assert helpers.helper(0) == 1


def test_helper_local_is_named_bar() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "helper"
    )
    locals_assigned = {
        node.id
        for node in ast.walk(function)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    }

    assert "foo" not in locals_assigned, "helper() still assigns a local named foo"
    assert "bar" in locals_assigned, "helper() must assign the renamed local bar"

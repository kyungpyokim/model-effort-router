"""Module-boundary check: billing helpers must live in billing, not core."""
from __future__ import annotations

import ast
from pathlib import Path

FIXTURE_ROOT = Path(__file__).resolve().parents[1]
BILLING_HELPERS = ("apply_tax", "format_invoice_total")
CALL_SITES = ("orders.py", "accounts.py")


def definition_files(helper: str) -> list[str]:
    """Fixture root files defining helper as a top-level function."""
    files: list[str] = []
    for path in sorted(FIXTURE_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.FunctionDef) and node.name == helper
            for node in tree.body
        ):
            files.append(path.name)
    return files


def import_sources(helper: str) -> dict[str, str]:
    """Call site -> module it imports helper from."""
    sources: dict[str, str] = {}
    for name in CALL_SITES:
        tree = ast.parse((FIXTURE_ROOT / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(
                alias.name == helper for alias in node.names
            ):
                sources[name] = node.module or ""
    return sources


def test_billing_helpers_are_defined_only_in_the_billing_module() -> None:
    for helper in BILLING_HELPERS:
        files = definition_files(helper)
        assert files == ["billing.py"], (
            f"{helper} must live only in billing.py, found in {files}"
        )


def test_call_sites_import_the_billing_helpers_from_the_billing_module() -> None:
    for helper in BILLING_HELPERS:
        sources = import_sources(helper)
        assert sources, f"no call site imports {helper}"
        wrong = {
            name: module for name, module in sources.items() if module != "billing"
        }
        assert wrong == {}, (
            f"call sites must import {helper} from billing, got {wrong}"
        )

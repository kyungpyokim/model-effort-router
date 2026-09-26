"""Consistency checks: the type rename must reach every service file."""
from __future__ import annotations

import ast
from pathlib import Path

FIXTURE_ROOT = Path(__file__).resolve().parents[1]
OLD_NAME = "UserProfileDTO"
NEW_NAME = "UserProfile"
SERVICE_FILES = [f"service_{index:02d}.py" for index in range(1, 11)]


def identifiers(path: Path) -> set[str]:
    """Every declared, referenced, or aliased identifier in one source file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.ClassDef):
            found.add(node.name)
        elif isinstance(node, ast.alias):
            found.add(node.asname or node.name.split(".")[0])
    return found


def files_referencing(name: str) -> list[str]:
    return sorted(
        str(path.relative_to(FIXTURE_ROOT))
        for path in FIXTURE_ROOT.rglob("*.py")
        if name in identifiers(path)
    )


def test_no_file_references_the_old_type_name() -> None:
    offenders = files_referencing(OLD_NAME)
    assert offenders == [], (
        f"the old type name must be renamed everywhere, still present in {offenders}"
    )


def test_models_defines_the_renamed_type() -> None:
    names = identifiers(FIXTURE_ROOT / "models.py")
    assert NEW_NAME in names, f"models.py must define {NEW_NAME}"


def test_all_ten_services_use_the_renamed_type() -> None:
    missing = [
        name
        for name in SERVICE_FILES
        if NEW_NAME not in identifiers(FIXTURE_ROOT / name)
    ]
    assert missing == [], f"services no longer using {NEW_NAME}: {missing}"

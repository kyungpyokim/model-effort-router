"""Acceptance checks for the README documentation."""
from pathlib import Path

README = Path(__file__).resolve().parents[1] / "README.md"


def test_readme_contains_no_known_typo() -> None:
    text = README.read_text(encoding="utf-8")

    assert "proejct" not in text, "README.md still contains the typo 'proejct'"


def test_readme_documents_the_correct_wording() -> None:
    text = README.read_text(encoding="utf-8")

    assert "project" in text, "README.md must describe the tool as a project"

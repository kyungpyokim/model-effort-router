"""Acceptance checks: unchanged behavior plus no unused imports."""
import ast
from pathlib import Path

import main

SOURCE = Path(__file__).resolve().parents[1] / "main.py"


def test_summarize_reports_word_counts() -> None:
    assert main.summarize("hello world") == '{"words": 2, "first": "hello"}'


def test_summarize_handles_empty_input() -> None:
    assert main.summarize("") == '{"words": 0, "first": ""}'


def test_main_module_has_no_unused_imports() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    imported = {
        alias.asname or alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    unused = sorted(imported - used)

    assert unused == [], f"unused imports in main.py: {unused}"

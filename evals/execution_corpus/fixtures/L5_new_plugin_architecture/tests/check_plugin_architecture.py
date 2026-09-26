"""Acceptance checks: dynamic plugin loading with isolated contexts."""
from __future__ import annotations

from pathlib import Path

import pytest

from plugin_loader import load_plugins

PLUGIN_DIR = str(Path(__file__).resolve().parents[1] / "plugins")


def test_loader_discovers_and_registers_every_plugin_dynamically() -> None:
    loaded = load_plugins(PLUGIN_DIR)
    assert sorted(loaded) == ["counter_plugin", "greet_plugin"]
    assert loaded["greet_plugin"]["greet"]("ada") == "hello, ada"
    assert loaded["counter_plugin"]["bump"]() == 1


def test_a_plugin_without_register_is_rejected(tmp_path) -> None:
    (tmp_path / "broken_plugin.py").write_text("VALUE = 1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_plugins(str(tmp_path))


def test_each_plugin_receives_its_own_context_object() -> None:
    loaded = load_plugins(PLUGIN_DIR)
    assert loaded["counter_plugin"] is not loaded["greet_plugin"], (
        "each plugin must be executed against its own isolated context"
    )


def test_one_plugins_state_is_invisible_to_another() -> None:
    loaded = load_plugins(PLUGIN_DIR)
    counter = loaded["counter_plugin"]
    greet = loaded["greet_plugin"]
    counter["bump"]()
    counter["bump"]()
    assert counter["calls"] == 2
    assert "calls" not in greet and "bump" not in greet, (
        f"plugin state leaked into another context: {sorted(greet)}"
    )
    assert greet["greet"]("lin") == "hello, lin"

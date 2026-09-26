"""Dynamic plugin loader that executes every plugin against one shared context."""
from __future__ import annotations

from pathlib import Path


def load_plugins(plugin_dir: str) -> dict[str, dict]:
    """Load every ``*.py`` plugin file, returning plugin name -> its context."""
    loaded: dict[str, dict] = {}
    shared_context: dict = {}
    for path in sorted(Path(plugin_dir).glob("*.py")):
        namespace: dict = {"__name__": f"plugins.{path.stem}", "__file__": str(path)}
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
        register = namespace.get("register")
        if register is None:
            raise ValueError(f"{path.name} must define register(ctx)")
        register(shared_context)
        loaded[path.stem] = shared_context
    return loaded

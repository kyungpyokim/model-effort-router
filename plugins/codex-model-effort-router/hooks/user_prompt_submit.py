#!/usr/bin/env python3
"""Advisory hook using the shared core; failures never block the prompt."""
import importlib.util
import os
import sys
from pathlib import Path

try:
    home = Path.home()
    xdg = Path(os.environ.get("XDG_DATA_HOME") or home / ".local/share")
    base = xdg if xdg.is_absolute() else home / ".local/share"
    runtime = Path(os.environ.get("MER_CORE_PATH") or base / "model-effort-router/runtime")
    package = runtime / "model_effort_router"
    if not runtime.is_absolute() or package.is_symlink() or not all((package / name).is_file() and not (package / name).is_symlink()
                                           for name in ("__init__.py", "entrypoints.py")):
        raise ImportError("shared core missing")
    sys.path.insert(0, str(runtime))
    from model_effort_router import entrypoints
    if entrypoints.RUNTIME_API != 1:
        raise RuntimeError("shared core API mismatch")
    plugin_root = Path(__file__).resolve().parent.parent
    router_path = plugin_root / "router.py"
    if router_path.is_symlink() or not router_path.is_file():
        raise ImportError("plugin router missing")
    spec = importlib.util.spec_from_file_location("_mer_codex_router", router_path)
    if spec is None or spec.loader is None:
        raise ImportError("plugin router unavailable")
    plugin_router = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plugin_router)
    CodexRouter = plugin_router.CodexRouter
    code = CodexRouter.run_hook(plugin_root)
except BaseException:
    code = 0
sys.exit(code)

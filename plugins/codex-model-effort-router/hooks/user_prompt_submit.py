#!/usr/bin/env python3
"""Advisory hook using the shared core; failures never block the prompt."""
import os
import sys
from pathlib import Path

try:
    home = Path.home()
    xdg = Path(os.environ.get("XDG_DATA_HOME") or home / ".local/share")
    base = xdg if xdg.is_absolute() else home / ".local/share"
    runtime = Path(os.environ.get("MER_CORE_PATH") or base / "model-effort-router/runtime")
    package = runtime / "model_effort_router"
    if not runtime.is_absolute() or package.is_symlink() or not all((package / name).is_file()
                                           for name in ("__init__.py", "entrypoints.py")):
        raise ImportError("shared core missing")
    sys.path.insert(0, str(runtime))
    from model_effort_router import entrypoints
    if entrypoints.RUNTIME_API != 1:
        raise RuntimeError("shared core API mismatch")
    code = entrypoints.hook("codex", Path(__file__).resolve().parent.parent, runtime_api=1)
except BaseException:
    code = 0
sys.exit(code)

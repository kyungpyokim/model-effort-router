#!/usr/bin/env python3
"""Codex UserPromptSubmit hook entry point; logic lives in the bundled model_effort_router package (fail-open)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from model_effort_router.host.codex_hooks import main
    code = main("UserPromptSubmit", ROOT)
except BaseException:  # import problems must never block the user's prompt or tool call
    code = 0
sys.exit(code)

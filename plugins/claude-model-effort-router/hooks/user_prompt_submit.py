#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook entry point; logic lives in the bundled model_effort_router package (fail-open).
Same advisory output as the Codex hook, with the Claude host (models, /model and /effort wording)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from model_effort_router.entrypoints import hook
    code = hook("claude", ROOT)
except BaseException:  # import problems must never block the user's prompt
    code = 0
sys.exit(code)

#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook entry point; logic lives in the bundled model_effort_router package (fail-open).
Same advisory output as the Codex hook, with the Claude host (models, /model and /effort wording)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["MER_HOST"] = "claude"  # this plugin is the Claude host, whatever the user's shell exports

try:
    from model_effort_router.host.codex_hooks import main
    code = main("UserPromptSubmit", ROOT)
except BaseException:  # import problems must never block the user's prompt
    code = 0
sys.exit(code)

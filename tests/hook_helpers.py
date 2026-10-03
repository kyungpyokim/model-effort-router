"""Run plugin scripts as Codex would: current python, JSON on stdin, clean MER_* env."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from model_effort_router.logging import route_log

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = Path(__file__).resolve().parent.parent / "plugins" / "codex-model-effort-router"
SID = "sess-0001"
DEV = "Fix the bug in parser.py ZEBRA_PROMPT_MARKER"


def run_script(rel, *, stdin="", env=None, cwd=None, argv=()):
    base = {k: v for k, v in os.environ.items() if not k.startswith(("MER_", "XDG_"))}
    base.update(env or {})
    return subprocess.run(
        [sys.executable, str(PLUGIN / rel), *argv], input=stdin, capture_output=True, text=True,
        env=base, cwd=cwd, timeout=60,
    )


class HookCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.state = self.root / "state"
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        self.fake = {"level": "L3"}
        self.write_repo_config({"difficulty": {"backend": "fake"}})

    def write_repo_config(self, cfg):
        (self.repo / ".model-effort-router.json").write_text(json.dumps(cfg))

    def env(self, **extra):
        e = {"MER_STATE_DIR": str(self.state), "HOME": str(self.home), "PYTHONPATH": str(ROOT),
             "MER_TEST_REGISTRY_MODULE": "tests.fake_registry", "MER_TEST_FAKE_BACKEND": json.dumps(self.fake)}
        e.update(extra)
        return e

    def submit(self, prompt=DEV, sid=SID, env_extra=None):
        payload = {"session_id": sid, "cwd": str(self.repo),
                   "hook_event_name": "UserPromptSubmit", "model": "gpt-6-luna",
                   "permission_mode": "default", "transcript_path": "/x", "prompt": prompt}
        return run_script("hooks/user_prompt_submit.py", stdin=json.dumps(payload),
                          env=self.env(**(env_extra or {})), cwd=str(self.root))

    def plugin_root(self):
        return PLUGIN

    def log_file(self, sid=SID):
        return Path(route_log.log_path(str(self.state), sid))

    def log_events(self, sid=SID):
        p = self.log_file(sid)
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []


def decision(proc):
    """None if the hook allowed silently, else the parsed hookSpecificOutput."""
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

from model_effort_router.host import codex_hooks
from tests.hook_helpers import HookCase, PLUGIN, ROOT, run_script

CLAUDE = ROOT / "plugins" / "claude-model-effort-router"
PROMPT = "Fix the login auth check in auth.py ZEBRA_PROMPT_TEXT"


class ManifestTest(unittest.TestCase):
    def test_plugin_manifest_hooks_and_marketplace(self):
        manifest = json.loads((CLAUDE / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(manifest["name"], "model-effort-router")
        hooks = json.loads((CLAUDE / "hooks" / "hooks.json").read_text())["hooks"]
        self.assertEqual(set(hooks), {"UserPromptSubmit"})  # advisory only: no PreToolUse
        cmd = hooks["UserPromptSubmit"][0]["hooks"][0]
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/user_prompt_submit.py", cmd["command"])
        self.assertEqual((cmd["type"], cmd["timeout"]), ("command", 30))
        market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
        (entry,) = market["plugins"]
        self.assertEqual((entry["name"], entry["source"]), ("model-effort-router", "./plugins/claude-model-effort-router"))
        self.assertTrue((ROOT / entry["source"] / ".claude-plugin" / "plugin.json").exists())

    def test_skill_and_wrappers(self):
        text = (CLAUDE / "skills" / "model-effort-router" / "SKILL.md").read_text()
        self.assertTrue(text.startswith("---\nname: model-effort-router\n"))
        for needle in ("/model", "/effort", "mer chat"):
            self.assertIn(needle, text)
        self.assertNotIn("spawn_agent", text)
        for name in ("mer", "mer-gate"):
            wrapper = CLAUDE / "bin" / name
            self.assertTrue(os.access(wrapper, os.X_OK), name)

    def test_wrapper_defaults_to_the_claude_host(self):
        with tempfile.TemporaryDirectory() as d:
            env = {k: v for k, v in os.environ.items() if not k.startswith("MER_")}
            env.update(MER_CORE_PATH=str(ROOT), HOME=d, MER_STATE_DIR=d)
            p = subprocess.run([sys.executable, str(CLAUDE / "bin" / "mer"), "run", "--dry-run", "--level", "L2", "--cwd", d,
                                "Fix the bug in calc.py"], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("host: claude", p.stdout)
        self.assertIn("first command: claude -p", p.stdout)

    def test_wrapper_ignores_an_exported_other_host_but_the_flag_wins(self):
        with tempfile.TemporaryDirectory() as d:
            env = {k: v for k, v in os.environ.items() if not k.startswith("MER_")}
            env.update(MER_CORE_PATH=str(ROOT), HOME=d, MER_STATE_DIR=d, MER_HOST="codex")
            def run(*extra):
                return subprocess.run([sys.executable, str(CLAUDE / "bin" / "mer"), "run", "--dry-run", "--level", "L2",
                                                             "--cwd", d, *extra, "Fix the bug in calc.py"], capture_output=True, text=True,
                                                            env=env, timeout=60).stdout
            self.assertIn("host: claude", run())
            self.assertIn("host: codex", run("--host", "codex"))

    def test_codex_entry_points_ignore_an_exported_claude_host(self):
        with tempfile.TemporaryDirectory() as d:
            env = {k: v for k, v in os.environ.items() if not k.startswith("MER_")}
            env.update(MER_CORE_PATH=str(ROOT), HOME=d, MER_STATE_DIR=d, MER_HOST="claude")
            p = subprocess.run([sys.executable, str(PLUGIN / "bin" / "mer"), "run", "--dry-run", "--level", "L2", "--cwd", d,
                                "Fix the bug in calc.py"], capture_output=True, text=True, env=env, timeout=60)
            self.assertIn("host: codex", p.stdout)
            self.assertIn("first command: codex exec", p.stdout)
            p = subprocess.run([sys.executable, str(PLUGIN / "bin" / "mer-gate"), "--cwd", d], capture_output=True, text=True,
                               env=env, timeout=60)
            self.assertEqual(p.returncode, 0, p.stderr)

    def test_codex_plugin_unchanged_default_host(self):
        with tempfile.TemporaryDirectory() as d:
            env = {k: v for k, v in os.environ.items() if not k.startswith("MER_")}
            env.update(MER_CORE_PATH=str(ROOT), HOME=d, MER_STATE_DIR=d)
            p = subprocess.run([sys.executable, str(PLUGIN / "bin" / "mer"), "run", "--dry-run", "--level", "L2", "--cwd", d,
                                "Fix the bug in calc.py"], capture_output=True, text=True, env=env, timeout=60)
        self.assertIn("host: codex", p.stdout)


class HookTest(HookCase):
    plugin = CLAUDE

    def setUp(self):
        super().setUp()
        self.home = self.root
        self.fake = {"level": "L4", "confidence": 0.62, "risk_flags": ["auth"]}

    def env(self, **extra):
        return super().env(**{"MER_HOST": "codex", **extra})

    def submit(self, prompt=PROMPT, payload=None, **extra):
        return super().submit(prompt, sid="s1", env_extra=extra, payload=payload)

    def log(self):
        return self.all_log_events()

    def test_advice_output_shape_and_claude_wording(self):
        p = self.submit()
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(set(out), {"hookSpecificOutput"})
        self.assertEqual(set(out["hookSpecificOutput"]), {"hookEventName", "additionalContext"})
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        c = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Difficulty: L4 (confidence 0.62). Risk flags: auth.", c)
        self.assertIn("Recommended session: claude-opus-5-5, effort high; switch with /model and /effort if you want.", c)
        self.assertIn("Plan first", c)
        self.assertIn("independent review (claude-opus-5-5, effort high)", c)
        self.assertIn(f"python3 {CLAUDE / 'bin' / 'mer'} run --review-profile frontier:high 'review only:", c)
        for banned in ("spawn_agent", "gpt-", "reasoning effort"):
            self.assertNotIn(banned, c)

    def user_default(self, model, effort):
        (self.root / ".claude").mkdir(exist_ok=True)
        (self.root / ".claude" / "settings.json").write_text(json.dumps({"model": model, "effortLevel": effort}))

    def test_silent_when_the_default_session_already_is_the_recommended_one(self):
        self.fake = {"level": "L2", "confidence": 0.9, "risk_flags": []}
        self.user_default("sonnet[1m]", "medium")  # the 1M-context alias is the same model
        prompt = "Rename the helper in utils.py and update its callers"  # no rule-based risk flag
        p = self.submit(prompt)
        self.assertEqual((p.returncode, p.stdout), (0, ""), p.stderr)
        self.assertEqual([e["decision"]["level"] for e in self.log() if e["event"] == "route"], ["L2"])  # still logged
        self.user_default("sonnet", "high")  # a different effort is still worth advising
        self.assertIn("Recommended session: claude-sonnet-5-5, effort medium", self.submit(prompt).stdout)

    def test_matching_default_drops_only_the_switch_line(self):
        self.user_default("claude-opus-5-5", "high")
        c = json.loads(self.submit().stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("Recommended session", c)
        self.assertIn("Plan first", c)
        self.assertIn("independent review", c)

    def test_log_event_without_prompt_text(self):
        self.submit()
        (ev,) = [e for e in self.log() if e["event"] == "route"]
        self.assertEqual((ev["target"], ev["decision"]["level"]), ("route", "L4"))
        self.assertNotIn("ZEBRA_PROMPT_TEXT", json.dumps(self.log()))

    def test_codex_hook_ignores_an_exported_claude_host(self):
        base = {k: v for k, v in os.environ.items() if not k.startswith(("MER_", "XDG_"))}
        base.update(self.env(MER_HOST="claude"))
        p = run_script("hooks/user_prompt_submit.py",
                       stdin=json.dumps({"session_id": "s1", "cwd": str(self.repo), "prompt": PROMPT}),
                       env=base, cwd=str(self.root))
        c = json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("gpt-6.1-sol, reasoning effort high", c)
        self.assertNotIn("claude-", c)

    def test_guard_is_a_noop(self):
        p = self.submit(MER_CLASSIFIER="1")
        self.assertEqual((p.returncode, p.stdout), (0, ""))
        self.assertFalse(self.state.exists())

    def test_no_route_and_off_are_silent(self):
        for prompt in ("What is the capital of France?", "/router off\n" + PROMPT):
            p = self.submit(prompt)
            self.assertEqual((p.returncode, p.stdout), (0, ""), prompt)

    def test_fail_open_on_garbage_bad_config_and_unknown_backend_data(self):
        self.assertEqual(self.submit(payload="not json").stdout, "")
        self.assertEqual(self.submit(payload={"cwd": str(self.repo)}).stdout, "")  # no prompt / session id
        (self.repo / ".model-effort-router.json").write_text("{not json")
        p = self.submit()
        self.assertEqual((p.returncode, p.stdout), (0, ""))
        self.assertTrue(any(e["event"] == "error" for e in self.log()))

    def test_fail_open_when_the_core_cannot_be_imported(self):
        base = {k: v for k, v in os.environ.items() if not k.startswith(("MER_", "XDG_"))}
        base.update(HOME=str(self.root), MER_CORE_PATH=str(self.root / "missing-runtime"))
        for plugin in (CLAUDE, PLUGIN):
            with self.subTest(plugin=plugin.name):
                broken = self.root / plugin.name
                (broken / "hooks").mkdir(parents=True)
                script = broken / "hooks" / "user_prompt_submit.py"
                script.write_text((plugin / "hooks" / script.name).read_text())
                p = subprocess.run([sys.executable, "-I", str(script)], input="{}", capture_output=True,
                                   text=True, env=base, cwd=self.root, timeout=60)
                self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))

    def test_main_in_process_fails_open_when_handler_raises(self):
        out = io.StringIO()
        old = codex_hooks.HANDLERS["UserPromptSubmit"]
        codex_hooks.HANDLERS["UserPromptSubmit"] = lambda *a: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            rc = codex_hooks.main("UserPromptSubmit", CLAUDE, stdin=io.StringIO(json.dumps({"session_id": "s"})), stdout=out,
                                  env=self.env())
        finally:
            codex_hooks.HANDLERS["UserPromptSubmit"] = old
        self.assertEqual((rc, out.getvalue()), (0, ""))

    def test_main_with_claude_host_env_in_process(self):
        out = io.StringIO()
        payload = {"session_id": "s", "cwd": str(self.repo), "prompt": PROMPT}
        rc = codex_hooks.main("UserPromptSubmit", CLAUDE, stdin=io.StringIO(json.dumps(payload)), stdout=out,
                              env=self.env(MER_HOST="claude"))
        self.assertEqual(rc, 0)
        self.assertIn("claude-opus-5-5", out.getvalue())

    def test_codex_hook_output_is_unchanged_for_the_default_host(self):
        out = io.StringIO()
        payload = {"session_id": "s", "cwd": str(self.repo), "prompt": PROMPT}
        env = self.env()
        del env["MER_HOST"]
        codex_hooks.main("UserPromptSubmit", PLUGIN, stdin=io.StringIO(json.dumps(payload)), stdout=out, env=env)
        c = json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"]
        self.assertIn("gpt-6.1-sol, reasoning effort high; switch with /model if you want.", c)


if __name__ == "__main__":
    unittest.main()

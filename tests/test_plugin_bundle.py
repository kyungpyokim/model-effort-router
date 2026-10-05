import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.sync_plugin import BUNDLES, check
from tests.hook_helpers import PLUGIN


class PluginBundleTest(unittest.TestCase):
    def test_bundle_and_skill_in_sync_with_core(self):
        self.assertEqual(check(), [], "run: python3 scripts/sync_plugin.py")

    def test_manifest_and_hooks_config(self):
        self.assertFalse((PLUGIN / "plugin.json").exists())  # root manifest makes Codex ignore hooks/skills
        manifest = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text())
        self.assertNotIn("$schema", manifest)
        self.assertEqual(manifest["name"], "model-effort-router")
        self.assertEqual((manifest["skills"], manifest["hooks"]), ("./skills/", "./hooks/hooks.json"))
        hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]
        self.assertEqual(set(hooks), {"UserPromptSubmit"})  # advisory only: no PreToolUse enforcement
        cmds = [h["command"] for g in hooks.values() for e in g for h in e["hooks"]]
        self.assertTrue(all("${CLAUDE_PLUGIN_ROOT}/hooks/" in c for c in cmds))
        self.assertGreaterEqual(hooks["UserPromptSubmit"][0]["hooks"][0]["timeout"], 20)  # > backend timeout_s
        self.assertFalse((PLUGIN / "hooks" / "pre_tool_use.py").exists())

    def test_skill_has_frontmatter(self):
        text = (PLUGIN / "skills" / "model-effort-router" / "SKILL.md").read_text()
        self.assertTrue(text.startswith("---\nname: model-effort-router\n"))
        self.assertNotIn("spawn_agent", text)  # the skill is advice, never a subagent protocol

    def test_loaders_delegate_to_shared_entrypoints(self):
        stub = '''import json
def cli(host):
    print(json.dumps(["cli", host]))
    return 13
def gate(host=None):
    print(json.dumps(["gate", host]))
    return 13
def hook(host, root):
    print(json.dumps(["hook", host, str(root)]))
    return 13
'''
        with tempfile.TemporaryDirectory() as temp:
            for bundle in BUNDLES:
                host = bundle.parent.name.split("-")[0]
                plugin = shutil.copytree(bundle.parent, Path(temp) / host)
                (plugin / "model_effort_router" / "entrypoints.py").write_text(stub)
                entries = [("bin/mer", ["cli", host]),
                           ("bin/mer-gate", ["gate", None if host == "antigravity" else host])]
                if host != "antigravity":
                    entries.append(("hooks/user_prompt_submit.py", ["hook", host, str(plugin)]))
                for script, expected in entries:
                    with self.subTest(host=host, script=script):
                        result = subprocess.run([sys.executable, "-I", str(plugin / script)],
                                                cwd=temp, input="{}", capture_output=True, text=True, timeout=30)
                        self.assertEqual(result.returncode, 13, result.stderr)
                        self.assertEqual(json.loads(result.stdout), expected)

    def test_copied_bundles_run_without_the_source_checkout(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workdir = root / "work"
            workdir.mkdir()
            env = {k: v for k, v in os.environ.items() if not k.startswith(("MER_", "XDG_"))}
            env = {**env, "HOME": temp, "MER_STATE_DIR": str(root / "state"), "MER_HOST": "claude"}
            for bundle in BUNDLES:
                host = bundle.parent.name.split("-")[0]
                plugin = shutil.copytree(bundle.parent, root / host)
                def run(script, *args):
                    return subprocess.run([sys.executable, "-I", str(plugin / script), *args], cwd=temp,
                                          env=env, capture_output=True, text=True, timeout=30)
                with self.subTest(host=host):
                    command = "chat" if host == "antigravity" else "run"
                    args = ["--dry-run", "--level", "L2", "--cwd", str(workdir), "Fix parser.py"]
                    result = run("bin/mer", command, *args)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(f"host: {host}", result.stdout)
                    other = "claude" if host == "codex" else "codex"
                    result = run("bin/mer", "run", "--host", other, *args)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(f"host: {other}", result.stdout)
                    result = run("bin/mer-gate", "--cwd", str(workdir))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout)["overall"], "incomplete")
                    if host == "antigravity":
                        result = run("bin/mer", "run", "--cwd", str(workdir), "Fix parser.py")
                        self.assertEqual(result.returncode, 2, result.stderr)
                        self.assertIn("run is not supported", result.stderr)


if __name__ == "__main__":
    unittest.main()

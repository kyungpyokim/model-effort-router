import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.install_core import install
from tests.hook_helpers import PLUGIN, ROOT

PLUGINS = [ROOT / "plugins" / f"{host}-model-effort-router" for host in ("codex", "claude", "antigravity")]


class PluginBundleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.runtime = self.root / "shared runtime"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("MER_", "XDG_", "PYTHONPATH"))}
        self.env = {**self.env, "HOME": str(self.root), "XDG_DATA_HOME": str(self.root / "data"),
                    "MER_CORE_PATH": str(self.runtime), "MER_STATE_DIR": str(self.root / "state"), "MER_HOST": "claude"}

    def run_loader(self, plugin, script, *args, env=None):
        return subprocess.run([sys.executable, "-I", str(plugin / script), *args], cwd=self.root,
                              env=self.env if env is None else env, input="{}", capture_output=True, text=True, timeout=30)

    def scripts(self, plugin):
        scripts = ["bin/mer", "bin/mer-gate"]
        if not plugin.name.startswith("antigravity"):
            scripts.append("hooks/user_prompt_submit.py")
        return scripts

    def test_plugins_have_no_core_implementation(self):
        for plugin in PLUGINS:
            self.assertFalse((plugin / "model_effort_router").exists(), plugin.name)

    def test_manifest_and_hooks_config(self):
        self.assertFalse((PLUGIN / "plugin.json").exists())
        manifest = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text())
        self.assertNotIn("$schema", manifest)
        self.assertEqual(manifest["name"], "model-effort-router")
        self.assertEqual((manifest["skills"], manifest["hooks"]), ("./skills/", "./hooks/hooks.json"))
        hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]
        self.assertEqual(set(hooks), {"UserPromptSubmit"})
        cmds = [h["command"] for g in hooks.values() for e in g for h in e["hooks"]]
        self.assertTrue(all("${CLAUDE_PLUGIN_ROOT}/hooks/" in c for c in cmds))
        self.assertGreaterEqual(hooks["UserPromptSubmit"][0]["hooks"][0]["timeout"], 20)
        self.assertFalse((PLUGIN / "hooks" / "pre_tool_use.py").exists())

    def test_skill_has_frontmatter(self):
        text = (PLUGIN / "skills" / "model-effort-router" / "SKILL.md").read_text()
        self.assertTrue(text.startswith("---\nname: model-effort-router\n"))
        self.assertNotIn("spawn_agent", text)

    def test_all_loaders_import_one_shared_core_and_forward_arguments(self):
        package = self.runtime / "model_effort_router"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("")
        (package / "entrypoints.py").write_text('''import json
from pathlib import Path
RUNTIME_API = 1
class RuntimeCompatibilityError(RuntimeError):
    pass
def report(args):
    print(json.dumps([str(Path(__file__).resolve()), args]))
    return 13
def cli(host, *, runtime_api):
    return report(["cli", host, runtime_api])
def gate(host=None, *, runtime_api):
    return report(["gate", host, runtime_api])
def hook(host, root, *, runtime_api):
    return report(["hook", host, str(root), runtime_api])
''')
        for source in PLUGINS:
            plugin = shutil.copytree(source, self.root / source.name)
            host = source.name.split("-")[0]
            expected = {"bin/mer": ["cli", host, 1], "bin/mer-gate": ["gate", None if host == "antigravity" else host, 1],
                        "hooks/user_prompt_submit.py": ["hook", host, str(plugin), 1]}
            for script in self.scripts(plugin):
                with self.subTest(host=host, script=script):
                    result = self.run_loader(plugin, script)
                    self.assertEqual(result.returncode, 13, result.stderr)
                    self.assertEqual(json.loads(result.stdout), [str(package / "entrypoints.py"), expected[script]])

    def test_installed_core_runs_copied_plugins_without_checkout_access(self):
        install(ROOT / "model_effort_router", self.runtime)
        for source in PLUGINS:
            plugin = shutil.copytree(source, self.root / source.name)
            host = source.name.split("-")[0]
            args = ["--dry-run", "--level", "L2", "--cwd", str(self.root), "Fix parser.py"]
            with self.subTest(host=host):
                result = self.run_loader(plugin, "bin/mer", "chat" if host == "antigravity" else "run", *args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("command: agy " if host == "antigravity" else f"host: {host}", result.stdout)
                other = "claude" if host == "codex" else "codex"
                result = self.run_loader(plugin, "bin/mer", "run", "--host", other, *args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"host: {other}", result.stdout)
                result = self.run_loader(plugin, "bin/mer-gate", "--cwd", str(self.root))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["overall"], "incomplete")
                if host == "antigravity":
                    result = self.run_loader(plugin, "bin/mer", "run", "--cwd", str(self.root), "Fix parser.py")
                    self.assertEqual(result.returncode, 2, result.stderr)
                else:
                    result = self.run_loader(plugin, "hooks/user_prompt_submit.py")
                    self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_default_xdg_runtime_and_relative_xdg_fallback(self):
        for xdg, runtime in ((str(self.root / "xdg"), self.root / "xdg/model-effort-router/runtime"),
                             ("relative", self.root / ".local/share/model-effort-router/runtime")):
            install(ROOT / "model_effort_router", runtime)
            env = {k: v for k, v in self.env.items() if k != "MER_CORE_PATH"}
            env["XDG_DATA_HOME"] = xdg
            for plugin in PLUGINS:
                result = self.run_loader(plugin, "bin/mer", "run", "--help", env=env)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_corrupt_relative_and_incompatible_core_fail_safely(self):
        package = self.runtime / "model_effort_router"
        for mode in ("missing", "relative", "corrupt", "incompatible"):
            env = dict(self.env)
            if mode == "relative":
                env["MER_CORE_PATH"] = "relative"
            elif mode in ("corrupt", "incompatible"):
                install(ROOT / "model_effort_router", self.runtime)
                if mode == "corrupt":
                    (package / "entrypoints.py").write_text("broken syntax!\n")
                else:
                    entry = package / "entrypoints.py"
                    entry.write_text(entry.read_text().replace("RUNTIME_API = 1", "RUNTIME_API = 999"))
            for plugin in PLUGINS:
                for script in self.scripts(plugin):
                    with self.subTest(mode=mode, plugin=plugin.name, script=script):
                        result = self.run_loader(plugin, script, env=env)
                        if script.startswith("hooks/"):
                            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
                        else:
                            self.assertEqual((result.returncode, result.stdout), (2, ""), result.stderr)
                            self.assertIn("shared core", result.stderr.lower())
                            self.assertNotIn("Traceback", result.stderr)

    def test_cwd_or_pythonpath_core_is_not_a_fallback(self):
        fake = self.root / "model_effort_router"
        fake.mkdir()
        (fake / "__init__.py").write_text('raise RuntimeError("CWD CORE WAS IMPORTED")')
        (fake / "entrypoints.py").write_text('raise RuntimeError("CWD CORE WAS IMPORTED")')
        for plugin in PLUGINS:
            result = subprocess.run([sys.executable, str(plugin / "bin/mer"), "run", "--help"],
                                    cwd=self.root, env={**self.env, "PYTHONPATH": str(self.root)},
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertNotIn("CWD CORE", result.stderr)

    def test_symlink_package_is_rejected_by_every_loader(self):
        install(ROOT / "model_effort_router", self.root / "external")
        self.runtime.mkdir()
        (self.runtime / "model_effort_router").symlink_to(self.root / "external/model_effort_router")
        for plugin in PLUGINS:
            for script in self.scripts(plugin):
                result = self.run_loader(plugin, script, "--help")
                if script.startswith("hooks/"):
                    self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
                else:
                    self.assertEqual((result.returncode, result.stdout), (2, ""), result.stderr)

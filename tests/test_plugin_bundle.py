import json
import unittest

from scripts.sync_plugin import check
from tests.hook_helpers import PLUGIN


class PluginBundleTest(unittest.TestCase):
    def test_bundle_and_skill_in_sync_with_core(self):
        self.assertEqual(check(), [], "run: python3 scripts/sync_plugin.py")

    def test_manifest_and_hooks_config(self):
        manifest = json.loads((PLUGIN / "plugin.json").read_text())
        self.assertEqual(manifest["name"], "model-effort-router")
        legacy = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text())
        self.assertEqual(legacy["name"], manifest["name"])
        hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]
        self.assertEqual(set(hooks), {"UserPromptSubmit", "PreToolUse"})
        cmds = [h["command"] for g in hooks.values() for e in g for h in e["hooks"]]
        self.assertTrue(all("${PLUGIN_ROOT}/hooks/" in c for c in cmds))
        self.assertGreaterEqual(hooks["UserPromptSubmit"][0]["hooks"][0]["timeout"], 20)  # > backend timeout_s
        self.assertIn("spawn_agent", hooks["PreToolUse"][0]["matcher"])

    def test_skill_has_frontmatter(self):
        text = (PLUGIN / "skills" / "model-effort-router" / "SKILL.md").read_text()
        self.assertTrue(text.startswith("---\nname: model-effort-router\n"))


if __name__ == "__main__":
    unittest.main()

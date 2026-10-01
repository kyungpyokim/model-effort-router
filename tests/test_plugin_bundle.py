import json
import unittest

from scripts.sync_plugin import check
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


if __name__ == "__main__":
    unittest.main()

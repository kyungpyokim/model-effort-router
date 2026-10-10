import json
import unittest

from tests.hook_helpers import ROOT


PLUGIN = ROOT / "plugins" / "opencode-model-effort-router"


class OpenCodePluginBundleTest(unittest.TestCase):
    def test_bundle_uses_shared_core_and_pins_current_plugin_api(self):
        package = json.loads((PLUGIN / "package.json").read_text())
        self.assertEqual(package["version"], "0.12.2")
        self.assertEqual(package["dependencies"]["@opencode/plugin"], "2.0.24")
        self.assertTrue((PLUGIN / "router.py").is_file())
        self.assertTrue((PLUGIN / "bin" / "mer").is_file())
        self.assertFalse((PLUGIN / "model_effort_router").exists())

    def test_plugin_registers_the_mer_tool_with_the_v2_api(self):
        source = (PLUGIN / "src" / "index.ts").read_text()
        self.assertIn('import { Plugin } from "@opencode/plugin"', source)
        self.assertIn('id: "model-effort-router"', source)
        self.assertIn('name: "mer"', source)
        self.assertIn("await ctx.tool.transform", source)
        self.assertNotIn("route_advice", source)
        route = (PLUGIN / "src" / "route.ts").read_text()
        self.assertIn('"--host"', route)
        self.assertIn('"opencode"', route)
        self.assertIn('"--json"', route)
        self.assertNotIn('"run"', route)


if __name__ == "__main__":
    unittest.main()

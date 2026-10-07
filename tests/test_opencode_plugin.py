import json
import unittest
from pathlib import Path

from tests.hook_helpers import ROOT


PLUGIN = ROOT / "plugins" / "opencode-model-effort-router"


class OpenCodePluginBundleTest(unittest.TestCase):
    def test_bundle_uses_shared_core_and_pins_stable_plugin_api(self):
        package = json.loads((PLUGIN / "package.json").read_text())
        self.assertEqual(package["dependencies"]["@opencode-ai/plugin"], "1.18.35")
        self.assertTrue((PLUGIN / "router.py").is_file())
        self.assertTrue((PLUGIN / "bin" / "mer").is_file())
        self.assertFalse((PLUGIN / "model_effort_router").exists())

    def test_plugin_registers_only_a_route_advice_tool(self):
        source = (PLUGIN / "src" / "index.ts").read_text()
        self.assertIn("import { tool } from \"@opencode-ai/plugin\"", source)
        self.assertIn("export const ModelEffortRouterPlugin", source)
        self.assertIn("route_advice:", source)
        route = (PLUGIN / "src" / "route.ts").read_text()
        self.assertIn('"--host", "opencode"', route)
        self.assertIn('"--json"', route)
        self.assertNotIn('"run"', route)


if __name__ == "__main__":
    unittest.main()

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.hook_helpers import ROOT, HookCase, run_script

PLUGIN = ROOT / "plugins" / "antigravity-model-effort-router"


class AntigravityBundleTest(unittest.TestCase):
    def test_native_manifest_has_expected_fields(self):
        manifest = json.loads((PLUGIN / "plugin.json").read_text())
        self.assertEqual(set(manifest), {"$schema", "name", "description"})
        self.assertEqual(manifest["name"], "model-effort-router")

    @unittest.skipUnless(shutil.which("agy"), "Antigravity CLI is not installed")
    def test_native_manifest_validates(self):
        checked = subprocess.run(["agy", "plugin", "validate", str(PLUGIN)], capture_output=True, text=True, timeout=30)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)

    def test_bundle_routes_but_rejects_unverified_worker_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            env = {k: v for k, v in os.environ.items() if not k.startswith("MER_")}
            env.update(MER_CORE_PATH=str(ROOT), HOME=str(root), MER_STATE_DIR=str(root / "state"))
            route = subprocess.run(
                [
                    sys.executable,
                    str(PLUGIN / "bin" / "mer"),
                    "route",
                    "--role",
                    "fix",
                    "--effort",
                    "medium",
                    "--json",
                    "--cwd",
                    str(root),
                    "Fix parser.py",
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            self.assertEqual(route.returncode, 0, route.stderr)
            self.assertEqual(json.loads(route.stdout)["role"], "fix")
            text = subprocess.run(
                [
                    sys.executable,
                    str(PLUGIN / "bin" / "mer"),
                    "route",
                    "--role",
                    "fix",
                    "--effort",
                    "medium",
                    "--cwd",
                    str(root),
                    "Fix parser.py",
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            self.assertEqual(text.returncode, 0, text.stderr)
            # The one display form everywhere: the plugin tag, then the pair with the effort shown separately.
            self.assertEqual(
                text.stdout.strip(), "[model-effort-router] fix → execution · gemini-3.8-flash · effort medium"
            )

    def test_pre_invocation_leads_with_the_tagged_pair(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            env = {k: v for k, v in os.environ.items() if not k.startswith("MER_")}
            env.update(MER_CORE_PATH=str(ROOT), HOME=str(root), MER_STATE_DIR=str(root / "state"))
            hook = subprocess.run(
                [sys.executable, str(PLUGIN / "hooks" / "pre_invocation.py")],
                input=json.dumps({"invocationNum": 0, "workspacePaths": [str(root)]}),
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                cwd=str(root),
            )
            self.assertEqual(hook.returncode, 0, hook.stderr)
            message = json.loads(hook.stdout)["injectSteps"][0]["ephemeralMessage"]
            # No role classification in this hook: the tagged model/effort pair still leads the message.
            self.assertTrue(
                message.startswith(
                    "[model-effort-router] gemini-3.8-flash · effort high; other configured options: "
                    "claude-sonnet-5-5 (user-selectable, not automatic fallbacks). "
                ),
                message,
            )
            run = subprocess.run(
                [
                    sys.executable,
                    str(PLUGIN / "bin" / "mer"),
                    "run",
                    "--role",
                    "fix",
                    "--effort",
                    "medium",
                    "--cwd",
                    str(root),
                    "Fix parser.py",
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            self.assertEqual(run.returncode, 2)
            self.assertIn("execution isolation is unverified", run.stderr)

    def test_bundle_has_native_skill_and_advisory_hook(self):
        skill = (PLUGIN / "skills" / "classify" / "SKILL.md").read_text()
        self.assertIn("mer route", skill)
        self.assertIn("mer run` is unsupported on this host", skill)
        hooks = json.loads((PLUGIN / "hooks.json").read_text())["model-effort-router"]
        self.assertEqual(set(hooks), {"PreInvocation"})
        self.assertTrue(os.access(PLUGIN / "bin" / "mer", os.X_OK))


class AntigravityRoutedHookTest(HookCase):
    plugin = PLUGIN

    def transcript(self, *requests):
        path = self.root / "transcript.jsonl"
        rows = [
            {
                "step_index": i,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "status": "DONE",
                "content": f"<USER_REQUEST>\n{text}\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\nnow\n</ADDITIONAL_METADATA>",
            }
            for i, text in enumerate(requests)
        ]
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        return path

    def hook(self, path, num=0):
        payload = {"invocationNum": num, "workspacePaths": [str(self.repo)], "transcriptPath": str(path)}
        out = run_script(
            "hooks/pre_invocation.py", stdin=json.dumps(payload), env=self.env(), cwd=self.repo, plugin=PLUGIN
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)["injectSteps"][0]["ephemeralMessage"] if out.stdout.strip() else None

    def test_routes_latest_user_request_into_execution_lane(self):
        self.fake = {"role": "fix", "effort": "medium"}
        message = self.hook(self.transcript("old question", "Fix the parser bug"))
        self.assertIn("fix \u2192 execution \u00b7 gemini-3.8-flash-medium \u00b7 effort medium", message)

    def test_routes_reasoning_roles_to_reasoning_lane_with_requested_effort(self):
        self.fake = {"role": "design", "effort": "high"}
        message = self.hook(self.transcript("Design the cache layer"))
        self.assertIn("design \u2192 reasoning \u00b7 gemini-4-argon-high \u00b7 effort high", message)

    def test_later_model_invocations_of_a_turn_stay_silent(self):
        self.assertIsNone(self.hook(self.transcript("Fix the parser bug"), num=1))

    def test_unreadable_transcript_keeps_the_static_advice(self):
        message = self.hook(self.root / "missing.jsonl")
        self.assertTrue(message.startswith("[model-effort-router] gemini-3.8-flash \u00b7 effort high"), message)

    def test_classifier_failure_reports_and_does_not_fall_back_to_static_advice(self):
        self.fake = {"raise": True}
        message = self.hook(self.transcript("Fix the parser bug"))
        self.assertIn("classifier failed", message)

    def test_effort_outside_the_hosts_range_is_clamped_not_dropped(self):
        for requested, applied in (("low", "medium"), ("xhigh", "high"), ("max", "high")):
            with self.subTest(requested=requested):
                self.fake = {"role": "fix", "effort": requested}
                message = self.hook(self.transcript("Fix the parser bug"))
                self.assertIn(f"gemini-3.8-flash-{applied} \u00b7 effort {applied}", message)

    def test_routing_error_is_reported_instead_of_silent(self):
        self.write_repo_config(
            {
                "difficulty": {"backend": "fake"},
                "models": {
                    "antigravity": {
                        "execution": {"primary": "gemini-3.8-flash", "fallback": None, "efforts": []},
                        "reasoning": {"primary": "gemini-4-argon", "fallback": None, "efforts": ["medium", "high"]},
                    }
                },
            }
        )
        message = self.hook(self.transcript("Fix the parser bug"))
        self.assertIn("routing error", message or "")

    def test_hook_injects_reply_tag_when_settings_change_present(self):
        self.fake = {"role": "fix", "effort": "medium"}
        path = self.root / "transcript_with_settings.jsonl"
        content = (
            "<USER_REQUEST>\nFix parser\n</USER_REQUEST>\n"
            "<USER_SETTINGS_CHANGE>\n"
            "The user changed setting `Model Selection` from None to Gemini 3.8 Flash (High).\n"
            "</USER_SETTINGS_CHANGE>"
        )
        row = {
            "step_index": 0,
            "source": "USER_EXPLICIT",
            "type": "USER_INPUT",
            "status": "DONE",
            "content": content,
        }
        path.write_text(json.dumps(row) + "\n")
        message = self.hook(path)
        self.assertIn(
            "start your first message of this turn with one line naming the model that will do the work:", message
        )
        self.assertIn("`[routed: gemini-3.8-flash-medium · effort medium]`", message)
        self.assertIn("`[main: gemini-3.8-flash · effort high]`", message)
        self.assertIn("(the Antigravity app does not show hook messages)", message)


if __name__ == "__main__":
    unittest.main()

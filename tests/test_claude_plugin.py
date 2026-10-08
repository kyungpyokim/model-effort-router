import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

from model_effort_router.difficulty.decision import EFFORTS, DifficultyDecision
from model_effort_router.host import advice, codex_hooks, hosts
from model_effort_router.policy.router import RoutePlan
from model_effort_router.policy.targeting import NO_ROUTE, ROUTE
from tests.hook_helpers import HookCase, PLUGIN, ROOT, run_script

CLAUDE = ROOT / "plugins" / "claude-model-effort-router"
PROMPT = "Fix the login auth check in auth.py ZEBRA_PROMPT_TEXT"


class ManifestTest(unittest.TestCase):
    def test_manifest_and_hook_are_advisory_only(self):
        manifest = json.loads((CLAUDE / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(manifest["name"], "model-effort-router")
        hooks = json.loads((CLAUDE / "hooks" / "hooks.json").read_text())["hooks"]
        self.assertEqual(set(hooks), {"UserPromptSubmit", "SessionStart", "PostModelSwitch"})
        cmd = hooks["UserPromptSubmit"][0]["hooks"][0]["command"]
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/user_prompt_submit.py", cmd)
        start = hooks["SessionStart"][0]["hooks"][0]
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/session_start.py", start["command"])
        self.assertLessEqual(start["timeout"], 10)
        switch = hooks["PostModelSwitch"][0]
        self.assertNotIn("matcher", switch)
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/post_model_switch.py", switch["hooks"][0]["command"])
        self.assertLessEqual(switch["hooks"][0]["timeout"], 10)
        skill = (CLAUDE / "skills" / "classify" / "SKILL.md").read_text()
        self.assertIn("Subagent", skill)
        self.assertIn("neither changes Main's model", skill)
        self.assertIn("--role", skill)
        self.assertIn("--effort", skill)
        for name in ("mer", "mer-gate"):
            self.assertTrue(os.access(CLAUDE / "bin" / name, os.X_OK))

    def test_host_wrappers_use_role_effort_and_pin_host(self):
        with tempfile.TemporaryDirectory() as d:
            env = {k: v for k, v in os.environ.items() if not k.startswith("MER_")}
            env.update(MER_CORE_PATH=str(ROOT), HOME=d, MER_STATE_DIR=d, MER_HOST="codex")
            cmd = [
                sys.executable,
                str(CLAUDE / "bin" / "mer"),
                "route",
                "--role",
                "fix",
                "--effort",
                "medium",
                "--json",
                "--cwd",
                d,
                "Fix the bug in calc.py",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["role"], "fix")
            codex = subprocess.run(
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
                    d,
                    "Fix the bug in calc.py",
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=60,
            )
            self.assertEqual(codex.returncode, 0, codex.stderr)

    def test_claude_and_codex_skill_contracts_are_host_specific(self):
        codex_skill = (PLUGIN / "skills" / "classify" / "SKILL.md").read_text()
        claude_skill = (CLAUDE / "skills" / "classify" / "SKILL.md").read_text()
        self.assertIn("gpt-6-luna", codex_skill)
        self.assertIn("claude-sonnet-5-5", claude_skill)


class EffortAgentTest(unittest.TestCase):
    def test_every_effort_has_an_agent_definition_with_matching_frontmatter(self):
        for effort in EFFORTS:
            text = (CLAUDE / "agents" / f"effort-{effort}.md").read_text()
            head = text.split("---")[1]
            with self.subTest(effort=effort):
                self.assertIn(f"name: effort-{effort}\n", head)
                self.assertIn(f"effort: {effort}\n", head)
                self.assertIn("Context Packet", text)
                self.assertIn("recursively", text)
                self.assertIn("Use only when the model-effort-router hook advice names this agent.", head)
        self.assertEqual(len(list((CLAUDE / "agents").glob("*.md"))), len(EFFORTS))

    def test_advice_names_agent_and_model_alias_for_claude_only(self):
        def plan(model, effort="high"):
            return RoutePlan(
                ROUTE,
                "auto",
                DifficultyDecision("review", "high", "x"),
                (),
                model,
                None,
                "reasoning",
                "high",
                effort,
                model_options=(model,),
            )

        for model, alias in (
            ("claude-opus-5-5", "opus"),
            ("claude-sonnet-5-5", "sonnet"),
            ("claude-fable-5-1", "fable"),
            ("opus", "opus"),
            ("sonnet-5-5", "sonnet"),
        ):
            note = advice.render(plan(model, "xhigh"), "mer", hosts.CLAUDE)
            self.assertIn(f'Agent(subagent_type="model-effort-router:effort-xhigh", model="{alias}")', note, model)
            self.assertEqual(model != alias, f"may differ from {model}" in note, model)
        self.assertNotIn("subagent_type", advice.render(plan("gpt-6.1-sol"), "mer", hosts.CODEX))

    def test_advice_without_alias_or_effort_support_names_no_effort_agent(self):
        def plan(model):
            return RoutePlan(
                ROUTE,
                "auto",
                DifficultyDecision("fix", "low", "x"),
                (),
                model,
                None,
                "execution",
                "low",
                "low",
                model_options=(model,),
            )

        note = advice.render(plan("provider/model-id"), "mer", hosts.CLAUDE)
        self.assertNotIn("subagent_type", note)
        self.assertNotIn("model=", note)
        self.assertIn(".claude/agents/", note)
        for model in ("claude-haiku-4-5", "haiku"):
            note = advice.render(plan(model), "mer", hosts.CLAUDE)
            self.assertIn('Agent(model="haiku")', note)
            self.assertNotIn("subagent_type", note)
            self.assertIn("effort does not apply", note)

    def test_advice_tells_main_agent_to_continue_on_no_route(self):
        decision = DifficultyDecision("fix", "low", "x", target="no_route")
        note = advice.render(RoutePlan(NO_ROUTE, "auto", decision), "mer", hosts.CLAUDE)
        self.assertEqual(note, advice.NO_ROUTE_MESSAGE)
        note = advice.render(
            RoutePlan(ROUTE, "auto", decision, (), "m", None, "execution", "low", "low"), "mer", hosts.CODEX
        )
        self.assertIn("handle it directly", note)


class HookTest(HookCase):
    plugin = CLAUDE

    def setUp(self):
        super().setUp()
        self.fake = {"role": "review", "effort": "medium", "confidence": 0.62}

    def submit_claude(self, prompt=PROMPT, **env):
        return self.submit(prompt, env_extra={"MER_HOST": "claude", **env})

    def test_hook_advises_without_changing_turn_settings(self):
        settings = self.home / ".claude" / "settings.json"
        settings.parent.mkdir()
        settings.write_text('{"model":"main-model","effortLevel":"high"}')
        original_settings = settings.read_bytes()
        proc = self.submit_claude()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        response = json.loads(proc.stdout)
        self.assertEqual(set(response), {"hookSpecificOutput", "systemMessage"})
        self.assertEqual(
            response["systemMessage"], "[model-effort-router] review → reasoning · claude-opus-5-5 · effort medium"
        )
        hook_output = response["hookSpecificOutput"]
        self.assertEqual(set(hook_output), {"hookEventName", "additionalContext"})
        self.assertEqual(hook_output["hookEventName"], "UserPromptSubmit")
        note = hook_output["additionalContext"]
        self.assertIn("review → reasoning · claude-opus-5-5 · effort medium", note)
        self.assertIn("claude-opus-5-5", note)
        self.assertIn('Agent(subagent_type="model-effort-router:effort-medium", model="opus")', note)
        self.assertIn("goal, decisions, constraints, actual diff, verification status/results", note)
        self.assertIn("native Subagent invocation", note)
        self.assertIn("not run", note)
        self.assertIn("does not change this Main turn", note)
        self.assertNotIn("L1", note)
        self.assertEqual(settings.read_bytes(), original_settings)

    def transcript_with(self, model):
        path = self.root / "t.jsonl"
        path.write_text(
            json.dumps(
                {
                    "type": "attachment",
                    "isSidechain": False,
                    "attachment": {"type": "model", "identity": {"modelId": model}},
                }
            )
            + "\n"
        )
        return str(path)

    def submit_with_transcript(self, model):
        data = {
            "session_id": "s",
            "cwd": str(self.repo),
            "prompt": PROMPT,
            "transcript_path": self.transcript_with(model),
        }
        return self.submit(payload=data, env_extra={"MER_HOST": "claude"})

    def test_main_model_from_a_real_format_transcript_selects_the_advice(self):
        match = json.loads(self.submit_with_transcript("claude-opus-5-5[1m]").stdout)
        self.assertIn(
            "Main already runs claude-opus-5-5; no Subagent needed", match["hookSpecificOutput"]["additionalContext"]
        )
        self.assertIn("proceeding without a Subagent", match["systemMessage"])
        miss = json.loads(self.submit_with_transcript("claude-sonnet-5-5").stdout)
        note = miss["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Main model claude-sonnet-5-5 ≠ routed claude-opus-5-5: spawn the Subagent", note)
        self.assertIn("Agent(subagent_type=", note)
        self.assertNotIn("proceeding without", miss["systemMessage"])

    def start_session(self, **extra):
        data = {"session_id": "s", "hook_event_name": "SessionStart", "source": "startup", **extra}
        return run_script(
            "hooks/session_start.py",
            stdin=json.dumps(data),
            env=self.env(MER_HOST="claude"),
            cwd=str(self.root),
            plugin=CLAUDE,
        )

    def switch_model(self, **extra):
        data = {"session_id": "s", "hook_event_name": "PostModelSwitch", "source": "command", **extra}
        return run_script(
            "hooks/post_model_switch.py",
            stdin=json.dumps(data),
            env=self.env(MER_HOST="claude"),
            cwd=str(self.root),
            plugin=CLAUDE,
        )

    def test_post_model_switch_updates_the_model_without_any_output(self):
        self.start_session(model="claude-sonnet-5-5")
        proc = self.switch_model(from_model="claude-sonnet-5-5", to_model="claude-opus-5-5")
        self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, "", ""))
        self.assertIn(
            "Main already runs claude-opus-5-5", self.first_prompt()["hookSpecificOutput"]["additionalContext"]
        )

    def test_post_model_switch_normalizes_snapshot_names_and_fails_open(self):
        self.switch_model(to_model="claude-haiku-4-5-20251001")
        (stored,) = [json.loads(p.read_text()) for p in self.state.glob("*.model")]
        self.assertEqual(stored.pop("ts") > 0, True)
        self.assertEqual(stored, {"model": "claude-haiku-4-5", "source": "switch"})
        proc = run_script(
            "hooks/post_model_switch.py",
            stdin="not json",
            env=self.env(MER_HOST="claude"),
            cwd=str(self.root),
            plugin=CLAUDE,
        )
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))

    def test_session_start_without_model_clears_a_switch_value(self):
        self.switch_model(to_model="claude-opus-5-5")
        self.start_session()
        self.assertEqual(list(self.state.glob("*.model")), [])

    def first_prompt(self):
        data = {"session_id": "s", "cwd": str(self.repo), "prompt": PROMPT, "transcript_path": "/no/such.jsonl"}
        return json.loads(self.submit(payload=data, env_extra={"MER_HOST": "claude"}).stdout)

    def test_session_start_model_decides_the_first_prompt_before_any_transcript_exists(self):
        proc = self.start_session(model="claude-opus-5-5")
        self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, "", ""))
        out = self.first_prompt()
        self.assertIn("Main already runs claude-opus-5-5", out["hookSpecificOutput"]["additionalContext"])
        self.start_session(model="claude-sonnet-5-5")
        self.assertIn(
            "Main model claude-sonnet-5-5 ≠ routed", self.first_prompt()["hookSpecificOutput"]["additionalContext"]
        )

    def test_session_start_without_model_clears_stale_value_and_stores_nothing_else(self):
        self.start_session(model="claude-opus-5-5")
        self.start_session()  # `claude -p`, /clear or a recovered conversation: no model field
        note = self.first_prompt()["hookSpecificOutput"]["additionalContext"]
        self.assertIn("handle it directly when Main's model/effort already match", note)
        stored = [p.read_text() for p in self.state.glob("*.model")]
        self.assertEqual(stored, [])

    def test_session_start_stores_only_the_model_name(self):
        self.start_session(model="claude-opus-5-5", prompt="ZEBRA_PROMPT_MARKER", cwd="/secret")
        files = list(self.state.iterdir())
        (stored,) = [json.loads(p.read_text()) for p in files]
        self.assertEqual(set(stored), {"model", "source", "ts"})
        self.assertEqual((stored["model"], stored["source"]), ("claude-opus-5-5", "start"))
        self.assertTrue(all(p.parent == self.state for p in files))

    def test_session_start_fails_open_on_garbage(self):
        proc = run_script(
            "hooks/session_start.py",
            stdin="not json",
            env=self.env(MER_HOST="claude"),
            cwd=str(self.root),
            plugin=CLAUDE,
        )
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))

    def test_codex_hook_uses_codex_model_mapping_even_if_claude_env_is_set(self):
        proc = run_script(
            "hooks/user_prompt_submit.py",
            stdin=json.dumps({"session_id": "s", "cwd": str(self.repo), "prompt": PROMPT}),
            env=self.env(MER_HOST="claude"),
            cwd=str(self.root),
            plugin=PLUGIN,
        )
        note = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("claude-", note)
        self.assertIn("gpt-6.1-sol", note)

    def test_guard_and_host_messages_are_silent_but_no_route_guides_main_agent(self):
        self.assertEqual(self.submit_claude(MER_CLASSIFIER="1").stdout, "")
        no_route = json.loads(self.submit_claude("What is the capital of France?").stdout)
        self.assertEqual(no_route["systemMessage"], advice.NO_ROUTE_MESSAGE)
        self.assertEqual([e["target"] for e in self.all_log_events()], ["no_route"])
        self.assertEqual(self.submit_claude("<task-notification>fix parser.py</task-notification>").stdout, "")
        self.assertEqual(len(self.all_log_events()), 1)

    def test_fail_open_for_garbage_missing_core_and_handler_errors(self):
        self.assertEqual(self.submit(payload="not json", env_extra={"MER_HOST": "claude"}).stdout, "")
        out = io.StringIO()
        old = codex_hooks.HANDLERS["UserPromptSubmit"]
        codex_hooks.HANDLERS["UserPromptSubmit"] = lambda *args: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            rc = codex_hooks.main(
                "UserPromptSubmit",
                CLAUDE,
                stdin=io.StringIO(json.dumps({"session_id": "s"})),
                stdout=out,
                env={"HOME": str(self.root)},
            )
        finally:
            codex_hooks.HANDLERS["UserPromptSubmit"] = old
        self.assertEqual((rc, out.getvalue()), (0, ""))

    def test_event_logs_hash_only(self):
        self.submit_claude()
        events = self.all_log_events()
        (event,) = [entry for entry in events if entry["event"] == "route"]
        self.assertEqual(event["decision"]["role"], "review")
        self.assertNotIn("ZEBRA_PROMPT_TEXT", json.dumps(events))
        self.assertNotIn("prompt", event)


if __name__ == "__main__":
    unittest.main()

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from model_effort_router.host import advice, codex_hooks
from model_effort_router.logging import route_log
from model_effort_router.policy.config import resolve_config
from model_effort_router.policy.router import route
from model_effort_router.policy.targeting import NO_ROUTE, ROUTE
from tests.hook_helpers import DEV, PLUGIN, SID, HookCase, run_script
from tests.test_claude_plugin import CLAUDE

POLICY = {"router": {"mode": "policy"}}
CODEX, CLAUDE_HOST = SimpleNamespace(name="codex"), SimpleNamespace(name="claude")


def boom():
    raise AssertionError("policy mode must not create a backend")


class PolicyRouteTest(unittest.TestCase):
    def test_config_accepts_policy(self):
        self.assertEqual(resolve_config(user=POLICY, registry={}).mode, "policy")

    def test_route_makes_no_backend_call(self):
        plan = route(DEV, user_config=POLICY, registry={"jev": boom, "nimble": boom})
        self.assertEqual((plan.target, plan.mode, plan.decision), (ROUTE, "policy", None))

    def test_every_nonblank_prompt_routes_and_prompt_override_enables_policy(self):
        for prompt in ("thanks!", "유져 늘었는지 서버 파악해봐"):  # no keyword prefilter: Main skips trivial ones
            self.assertEqual(route(prompt, user_config=POLICY, registry={}).target, ROUTE)
        self.assertEqual(route("   ", user_config=POLICY, registry={}).target, NO_ROUTE)
        plan = route("/router policy\n" + DEV, registry={"jev": boom, "nimble": boom})
        self.assertEqual((plan.target, plan.mode), (ROUTE, "policy"))

    def test_explicit_override_keeps_classic_plan(self):
        plan = route("/router role=fix effort=low\n" + DEV, user_config=POLICY, registry={})
        self.assertEqual((plan.mode, plan.decision.role, plan.agent), ("policy", "fix", "execution"))
        self.assertFalse(advice.is_policy(plan))


class PolicyAdviceTest(unittest.TestCase):
    lanes = resolve_config(user=POLICY, registry={}).models

    def test_codex_text(self):
        text = advice.render_policy(self.lanes["codex"], CODEX, "gpt-6-luna")
        for part in (
            "gpt-6-luna",
            "gpt-6.1-sol",
            "spawn_agent(",
            "Do not pass agent_type",
            "`[routed:",
            "`[main: gpt-6-luna]`",
        ):
            self.assertIn(part, text)

    def test_claude_text_has_the_desktop_app_tag(self):
        text = advice.render_policy(self.lanes["claude"], CLAUDE_HOST, "claude-opus-5-5")
        for part in (
            "claude-sonnet-5-5",
            "claude-opus-5-5",
            'Agent(subagent_type="model-effort-router:effort-<effort>"',
        ):
            self.assertIn(part, text)
        self.assertIn("`[routed: <lane model> · effort <effort>]`", text)
        self.assertIn("`[main: claude-opus-5-5]`", text)
        self.assertIn("the Claude desktop app does not show hook messages", text)

    def test_unknown_main_model_uses_placeholder(self):
        text = advice.render_policy(self.lanes["codex"], CODEX, None)
        self.assertIn("`[main: <your model>]`", text)
        self.assertNotIn("None", text)

    def test_summary(self):
        self.assertEqual(
            advice.policy_summary(self.lanes["codex"], "gpt-6-luna"),
            {
                "action": "policy",
                "main_model": "gpt-6-luna",
                "lanes": {"execution": "gpt-6-luna", "reasoning": "gpt-6.1-sol"},
            },
        )


class PolicyCorrelationTest(unittest.TestCase):
    def matched(self, models, agent_type):
        expected = {"action": "policy", "models": models}
        return codex_hooks._expected_matches(expected, "claude", agent_type, None)

    def test_haiku_lane_and_non_string_agent_type_are_not_comparable(self):
        self.assertIsNone(self.matched(["claude-haiku-4-5", "claude-opus-5-5"], "model-effort-router:effort-high"))
        self.assertIsNone(self.matched(["claude-sonnet-5-5"], 123))
        self.assertIs(self.matched(["claude-sonnet-5-5"], "Explore"), False)


class PolicyHookTest(HookCase):
    def setUp(self):
        super().setUp()
        self.write_repo_config({"router": {"mode": "policy"}, "difficulty": {"backend": "fake"}})
        self.fake = {"raise": True}  # any classifier call would fail the route

    def route(self, plugin=PLUGIN, host="codex", model="gpt-6-luna", prompt=DEV):
        payload = {"session_id": SID, "cwd": str(self.repo), "prompt": prompt, "model": model}
        proc = run_script(
            "hooks/user_prompt_submit.py",
            stdin=json.dumps(payload),
            env=self.env(MER_HOST=host),
            cwd=str(self.root),
            plugin=plugin,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc, [e for e in self.log_events() if e["event"] == "route"][-1]

    def start(self, plugin, host, **data):
        for script in ("subagent_start", "subagent_stop"):
            proc = run_script(
                f"hooks/{script}.py",
                stdin=json.dumps({"session_id": SID, "agent_id": "a1", **data}),
                env=self.env(MER_HOST=host),
                cwd=str(self.root),
                plugin=plugin,
            )
            self.assertEqual((proc.returncode, proc.stdout), (0, ""))
            if script == "subagent_start":
                start = self.log_events()[-1]["correlation"]
        return start

    def test_codex_route_logs_policy_and_correlates_on_lane_models(self):
        proc, ev = self.route()
        out = json.loads(proc.stdout)
        self.assertIn("policy ·", out["systemMessage"])
        self.assertIn("lane", out["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(ev["mode"], "policy")
        self.assertEqual(ev["advice"]["action"], "policy")
        self.assertNotIn("classifier_usage", ev)
        corr = self.start(PLUGIN, "codex", model="gpt-6.1-sol")
        self.assertIs(corr["matched"], True)
        self.assertIs(self.start(PLUGIN, "codex", model="other")["matched"], False)
        self.assertIsNone(self.start(PLUGIN, "codex")["matched"])

    def test_claude_correlates_on_effort_agent_prefix(self):
        self.route(CLAUDE, "claude", "claude-opus-5-5")
        self.assertIs(self.start(CLAUDE, "claude", agent_type="model-effort-router:effort-high")["matched"], True)
        self.assertIs(self.start(CLAUDE, "claude", agent_type="Explore")["matched"], False)
        self.assertIsNone(self.start(CLAUDE, "claude")["matched"])

    def test_no_route_prompt_is_silent(self):
        proc, ev = self.route(prompt="   ")
        self.assertEqual((proc.stdout, ev["advice"]), ("", {"action": "no_route"}))


class CompareModesTest(HookCase):
    def test_report_groups_by_mode_and_host(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        import compare_modes

        def ev(**kw):
            return {"ts": 10, **kw}

        route_log.append(
            str(self.state),
            "s1",
            ev(event="route", mode="policy", host="codex", target="route", latency_ms=4, advice={"action": "policy"}),
        )
        route_log.append(str(self.state), "s1", ev(event="subagent_start", correlation={"matched": True}))
        route_log.append(str(self.state), "s1", ev(event="route", target="error", error_type="X"))
        route_log.append(str(self.state), "s1", ev(event="subagent_start", correlation={"matched": False}))
        route_log.append(
            str(self.state),
            "s2",
            ev(
                event="route",
                mode="auto",
                host="codex",
                target="route",
                latency_ms=900,
                classifier_usage={"input_tokens": 5, "output_tokens": 2},
                advice={"action": "spawn"},
            ),
        )
        route_log.append(
            str(self.state),
            "s2",
            ev(
                event="route",
                mode="auto",
                host="codex",
                target="no_route",
                latency_ms=100,
                advice={"action": "no_route"},
            ),
        )
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            compare_modes.report(compare_modes.collect(str(self.state)))
        rows = {line.split()[0]: line.split() for line in buf.getvalue().splitlines()[1:]}
        self.assertEqual(rows["policy"][2:], ["1", "1", "1", "1/0/0", "4", "0"])
        self.assertEqual(rows["auto"][2:], ["1", "1", "0", "0/0/0", "500", "7"])


if __name__ == "__main__":
    unittest.main()

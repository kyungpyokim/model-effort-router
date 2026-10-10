import json
import unittest
from types import SimpleNamespace

from model_effort_router.difficulty.decision import DifficultyDecision
from model_effort_router.host import advice, codex_hooks
from model_effort_router.logging import route_log
from model_effort_router.policy.router import RoutePlan
from model_effort_router.policy.targeting import NO_ROUTE, ROUTE
from tests.hook_helpers import DEV, PLUGIN, SID, HookCase, run_script
from tests.test_claude_plugin import CLAUDE

FAKE = {"role": "review", "effort": "medium", "confidence": 0.8}


class WorkflowLogTest(HookCase):
    def route(self, **extra):
        self.fake = FAKE
        data = {"session_id": SID, "cwd": str(self.repo), "prompt": DEV, "turn_id": "t1", "model": "gpt-6-luna"}
        self.assertEqual(self.submit(payload={**data, **extra}).returncode, 0)
        return [e for e in self.log_events() if e["event"] == "route"][-1]

    def sub(self, event, plugin=PLUGIN, host="codex", **data):
        payload = {"session_id": SID, "agent_id": "a1", "agent_type": "worker", **data}
        script = "hooks/subagent_start.py" if event == "start" else "hooks/subagent_stop.py"
        proc = run_script(
            script, stdin=json.dumps(payload), env=self.env(MER_HOST=host), cwd=str(self.root), plugin=plugin
        )
        self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, "", ""))
        return self.log_events()[-1]

    def test_route_event_records_host_turn_and_spawn_advice(self):
        ev = self.route()
        self.assertEqual((ev["host"], ev["turn_id"]), ("codex", "t1"))
        self.assertEqual(
            ev["advice"],
            {
                "action": "spawn",
                "main_model": "gpt-6-luna",
                "routed_model": "gpt-6.1-sol",
                "routed_effort": "medium",
                "agent": "reasoning",
                "invocation": {"model": "gpt-6.1-sol", "reasoning_effort": "medium"},
            },
        )
        self.assertNotIn("ZEBRA_PROMPT_MARKER", json.dumps(ev))

    def test_same_model_and_unknown_main_actions(self):
        self.assertEqual(self.route(model="gpt-6.1-sol")["advice"]["action"], "inline_same_model")
        self.assertIsNone(self.route(model="gpt-6.1-sol")["advice"]["invocation"])
        self.assertEqual(self.route(model=None)["advice"]["action"], "advise")

    def test_subagent_start_and_stop_correlate_with_the_route(self):
        self.route()
        start = self.sub("start", model="gpt-6.1-sol", turn_id="child-turn")
        self.assertEqual(
            (start["event"], start["host"], start["agent_id"], start["model"]),
            ("subagent_start", "codex", "a1", "gpt-6.1-sol"),
        )
        self.assertEqual((start["agent_turn_id"], "turn_id" in start), ("child-turn", False))
        self.assertEqual(start["correlation"]["expected"]["model"], "gpt-6.1-sol")
        self.assertIs(start["correlation"]["matched"], True)
        self.assertEqual(start["correlation"]["matched_on"], ["model"])
        stop = self.sub("stop", model="gpt-6.1-sol", last_assistant_message="SECRET_REPLY")
        self.assertEqual(stop["event"], "subagent_stop")
        self.assertEqual(stop["correlation"], start["correlation"])
        self.assertNotIn("SECRET_REPLY", json.dumps(self.log_events()))

    def test_wrong_model_does_not_match_and_no_route_is_null(self):
        self.assertIsNone(self.sub("start", model="gpt-6.1-sol")["correlation"]["matched"])  # no route yet
        self.route()
        self.assertIs(self.sub("start", model="other")["correlation"]["matched"], False)
        self.assertIsNone(self.sub("start")["correlation"]["matched"])  # model unknown

    def test_claude_matches_on_agent_type(self):
        self.fake = FAKE
        payload = {"session_id": SID, "cwd": str(self.repo), "prompt": DEV, "model": "claude-sonnet-5-5"}
        run_script(
            "hooks/user_prompt_submit.py",
            stdin=json.dumps(payload),
            env=self.env(MER_HOST="claude"),
            cwd=str(self.root),
            plugin=CLAUDE,
        )
        adv = [e for e in self.log_events() if e["event"] == "route"][-1]["advice"]
        self.assertEqual(adv["invocation"], {"subagent_type": "model-effort-router:effort-medium", "model": "opus"})
        ok = self.sub("start", CLAUDE, "claude", agent_type="model-effort-router:effort-medium")
        self.assertIs(ok["correlation"]["matched"], True)
        self.assertEqual(ok["correlation"]["matched_on"], ["agent_type"])
        bad = self.sub("start", CLAUDE, "claude", agent_type="Explore")
        self.assertIs(bad["correlation"]["matched"], False)

    def test_stop_follows_its_own_start_not_the_latest_route(self):
        self.route()
        self.sub("start", model="gpt-6.1-sol", agent_id="a1")
        self.route(model="gpt-6.1-sol")  # a later prompt: Main inline
        stop = self.sub("stop", model="gpt-6.1-sol", agent_id="a1")
        self.assertEqual(stop["correlation"]["expected"]["action"], "spawn")
        self.assertIs(stop["correlation"]["matched"], True)
        orphan = self.sub("stop", agent_id="other")
        self.assertEqual(orphan["correlation"], {"expected": None, "matched": None, "matched_on": []})

    def test_inline_same_model_route_never_claims_a_match(self):
        self.route(model="gpt-6.1-sol")
        start = self.sub("start", model="gpt-6.1-sol")
        self.assertEqual(start["correlation"]["expected"]["action"], "inline_same_model")
        self.assertIsNone(start["correlation"]["matched"])

    def test_claude_haiku_route_is_not_comparable(self):
        expected = {
            "model": "claude-haiku-4-5",
            "action": "spawn",
            "invocation": {"subagent_type": None, "model": "haiku"},
        }
        self.assertIsNone(codex_hooks._expected_matches(expected, "claude", "anything", None))

    def test_unicode_line_separators_do_not_split_log_lines(self):
        self.state.mkdir(parents=True)
        route_log.append(str(self.state), SID, {"event": "route", "n": 1})
        route_log.append(
            str(self.state), SID, {"event": "subagent_start", "agent_id": "a", "agent_type": "x\u2028y\x85z"}
        )
        with open(self.log_file(), "a", encoding="utf-8") as f:  # raw separators, as a non-escaping writer would emit
            f.write('{"event": "subagent_start", "agent_id": "b", "agent_type": "p\u2028q\x85r"}\n')
        found = route_log.last_event(str(self.state), SID, "subagent_start", agent_id="b")
        self.assertEqual(found["agent_type"], "p\u2028q\x85r")
        self.assertEqual(route_log.last_event(str(self.state), SID, "route")["n"], 1)

    def test_route_line_straddling_the_tail_boundary_is_skipped_not_misread(self):
        self.state.mkdir(parents=True)
        sdir = str(self.state)
        route_log.append(sdir, SID, {"event": "route", "n": 1, "pad": "y" * 200})
        while self.log_file().stat().st_size < route_log.TAIL_BYTES - 100:
            route_log.append(sdir, SID, {"event": "run", "pad": "x" * 100})
        route_log.append(sdir, SID, {"event": "run", "pad": "z" * 400})
        route_log.append(sdir, SID, {"event": "run", "pad": "x" * 100})
        self.assertIsNone(route_log.last_event(sdir, SID, "route"))  # n=1 lies outside the tail

    def test_corrupt_log_and_missing_session_fail_open(self):
        self.state.mkdir(parents=True)
        self.log_file().write_text("{broken\n")
        self.assertIsNone(route_log.last_event(str(self.state), SID, "route"))
        payload = {"session_id": SID, "agent_id": "a1"}
        proc = run_script("hooks/subagent_start.py", stdin=json.dumps(payload), env=self.env(), cwd=str(self.root))
        self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, "", ""))
        last = json.loads(self.log_file().read_text().splitlines()[-1])
        self.assertIsNone(last["correlation"]["matched"])
        proc = run_script("hooks/subagent_stop.py", stdin="{}", env=self.env(), cwd=str(self.root))
        self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, "", ""))

    def test_last_route_reads_only_the_tail(self):
        self.state.mkdir(parents=True)
        route_log.append(str(self.state), SID, {"event": "route", "n": 1})
        for _ in range(3000):
            route_log.append(str(self.state), SID, {"event": "run", "pad": "x" * 100})
        self.assertIsNone(route_log.last_event(str(self.state), SID, "route"))
        route_log.append(str(self.state), SID, {"event": "route", "n": 2})
        self.assertEqual(route_log.last_event(str(self.state), SID, "route")["n"], 2)


def _plan(model, effort="medium", target=ROUTE, mode="auto", decision=True):
    return RoutePlan(
        target,
        mode,
        DifficultyDecision("fix", effort, "x") if decision else None,
        (),
        model,
        None,
        "reasoning",
        effort,
        effort,
        model_options=(model,),
    )


def _host(name):
    return SimpleNamespace(name=name)


class InvocationAgreementTest(unittest.TestCase):
    CASES = (
        ("codex spawn", "codex", "gpt-6.1-sol", "gpt-6-luna", "spawn"),
        ("codex advise", "codex", "gpt-6.1-sol", None, "advise"),
        ("claude alias spawn", "claude", "claude-opus-5-5", "claude-sonnet-5-5", "spawn"),
        ("claude alias advise", "claude", "claude-opus-5-5", None, "advise"),
        ("claude haiku", "claude", "claude-haiku-4-5", "claude-sonnet-5-5", "spawn"),
        ("claude no alias", "claude", "other-model", "claude-sonnet-5-5", "advise"),
    )

    def test_logged_invocation_values_appear_in_the_rendered_advice(self):
        for label, host, model, main, action in self.CASES:
            with self.subTest(label):
                plan, h = _plan(model), _host(host)
                info, text = advice.summary(plan, h, main), advice.render(plan, "mer", h, main)
                self.assertEqual(info["action"], action)
                invocation = info["invocation"]
                if invocation is None:
                    self.assertTrue("invoke:" not in text or "has no Agent model alias" in text)
                    continue
                for key, value in invocation.items():
                    if value is not None:
                        self.assertIn(f'{key}="{value}"', text)
                if label == "claude haiku":
                    self.assertIn('invoke: Agent(model="haiku")', text)

    def test_every_no_route_plan_logs_no_route_and_only_a_missing_decision_logs_off(self):
        for mode in ("auto", "manual", "off", "invalid_override"):
            plan = RoutePlan(NO_ROUTE, mode)
            self.assertEqual(advice.summary(plan, _host("codex"))["action"], "no_route", mode)
        self.assertEqual(advice.summary(_plan("m", decision=False), _host("codex"))["action"], "off")

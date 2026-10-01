import io
import json
import unittest
from contextlib import redirect_stdout

from model_effort_router import cli
from model_effort_router.difficulty.decision import DifficultyDecision
from model_effort_router.flow import SELF_CHECK, SUBAGENT_HINT
from model_effort_router.host import codex_exec as cx
from model_effort_router.policy.config import resolve_config
from model_effort_router.policy.session import IMPLEMENT_SUBAGENTS, REVIEW_SUBAGENTS, session_plan
from model_effort_router.profiles.profiles import Profile
from tests.test_eval_live_runner import Env
from tests.test_mer_cli import CliCase
from tests.test_mer_flow import GATE_BAD, GATE_OK, REQ, Harness

OFF = ["-c", "agents.enabled=false"]
ONE = ["-c", "agents.enabled=true", "-c", "agents.max_concurrent_threads_per_session=1"]


def flags(argv):
    """The agents.* -c overrides of a codex argv, in order."""
    return [x for i, x in enumerate(argv) if x.startswith("agents.") or (x == "-c" and argv[i + 1].startswith("agents."))]


def has(argv, expected):
    return flags(argv) == expected


class ArgvTest(unittest.TestCase):
    P = Profile("balanced", "high")

    def test_agents_flags(self):
        self.assertEqual(cx.agents_flags(None), [])
        self.assertEqual(cx.agents_flags(0), OFF)
        self.assertEqual(cx.agents_flags(1), ONE)
        self.assertEqual(cx.agents_flags(3)[-1], "agents.max_concurrent_threads_per_session=3")

    def test_session_and_resume_argv(self):
        for n, expected in ((None, []), (0, OFF), (1, ONE)):
            with self.subTest(n=n):
                self.assertEqual(flags(cx.session_argv(self.P, "p", "workspace-write", subagents=n)), expected)
                self.assertEqual(flags(cx.resume_argv(self.P, "T", "p", subagents=n)), expected)
        argv = cx.session_argv(self.P, "do it", "read-only", subagents=0)
        self.assertEqual(argv[-1], "do it")  # the prompt stays last
        self.assertEqual(cx.resume_argv(self.P, "T", "go", subagents=0)[-2:], ["T", "go"])
        self.assertEqual(cx.session_argv(self.P, "p", "read-only"), cx.session_argv(self.P, "p", "read-only", subagents=None))

    def test_no_policy_reproduces_the_argv_from_before_the_policy(self):
        r = cx.resolve(self.P, cx.CodexConfig())
        head = ["codex", "exec"]
        tail = ["--json", "--skip-git-repo-check"]
        effort = ["-m", r.model, "-c", f"model_reasoning_effort={r.applied_effort}"]
        self.assertEqual(cx.session_argv(self.P, "p", "read-only", subagents=None),
                         head + tail + ["-s", "read-only"] + effort + ["p"])
        self.assertEqual(cx.resume_argv(self.P, "T", "p", subagents=None),
                         head + ["resume"] + tail + effort + ["-c", 'sandbox_mode="workspace-write"', "T", "p"])


class PlanTest(unittest.TestCase):
    def sp(self, level, policy="level", flags=()):
        return session_plan(DifficultyDecision(level, "f", risk_flags=flags), flags, None, policy)

    def test_table_per_level(self):
        self.assertEqual(IMPLEMENT_SUBAGENTS, {"L1": 0, "L2": 0, "L3": 0, "L4": 0, "L5": 1})
        for level, n in IMPLEMENT_SUBAGENTS.items():
            sp = self.sp(level)
            self.assertEqual((sp.implement_subagents, sp.review_subagents), (n, REVIEW_SUBAGENTS))

    def test_codex_policy_leaves_everything_to_codex(self):
        for level in IMPLEMENT_SUBAGENTS:
            sp = self.sp(level, "codex")
            self.assertEqual((sp.implement_subagents, sp.review_subagents), (None, None))

    def test_manual_mode_has_no_flags(self):
        sp = session_plan(None, (), {"session": Profile("frontier", "high")})
        self.assertEqual((sp.implement_subagents, sp.review_subagents), (None, 0))  # review is always off
        self.assertEqual(session_plan(None, (), {"session": Profile("frontier", "high")}, "codex").review_subagents, None)

    def test_in_to_dict(self):
        d = self.sp("L5").to_dict()
        self.assertEqual((d["implement_subagents"], d["review_subagents"]), (1, 0))


class FlowTest(unittest.TestCase):
    def test_implement_flags_per_level_and_prompt_hint_only_for_l5(self):
        for level, expected in (("L1", OFF), ("L2", OFF), ("L3", OFF), ("L4", OFF), ("L5", ONE)):
            with self.subTest(level=level):
                h = Harness()
                r = h.run(level)
                argv = h.calls[0]["argv"]
                self.assertTrue(has(argv, expected))
                self.assertEqual(SUBAGENT_HINT in argv[-1], level == "L5")
                self.assertEqual(r["calls"][0]["subagents"], IMPLEMENT_SUBAGENTS[level])
        self.assertIn("never to parallelise code search, test runs or repeated checks", SUBAGENT_HINT)

    def test_self_check_hint_only_when_subagents_are_off(self):
        for level, policy, expected in (("L1", "level", True), ("L4", "level", True), ("L5", "level", False),
                                        ("L3", "codex", False)):
            with self.subTest(level=level, policy=policy):
                h = Harness()
                h.run(level, policy=policy)
                self.assertEqual(SELF_CHECK in h.calls[0]["argv"][-1], expected)
        self.assertIn("fail on the code before your change", SELF_CHECK)

    def test_review_prompt_asks_for_test_strength_and_partial_state(self):
        from model_effort_router.review import review_prompt
        text = review_prompt("r", {"diff": "", "is_repo": True}, {})
        self.assertIn("tests that would still pass without the change", text)
        self.assertIn("state changed before an error is raised", text)

    def test_escalations_keep_the_implement_policy(self):
        h = Harness(gates=(GATE_BAD, GATE_BAD, GATE_OK))
        r = h.run("L2")
        self.assertEqual(len(h.calls), 3)
        for c in h.calls:
            self.assertTrue(has(c["argv"], OFF))
        self.assertEqual([c["subagents"] for c in r["calls"]], [0, 0, 0])

    def test_l5_resume_keeps_one_subagent_cap(self):
        h = Harness(gates=(GATE_BAD,), verdicts=[("changes_requested", 1)])
        r = h.run("L5", max_escalations=1)
        self.assertEqual([c["role"] for c in r["calls"]][:1], ["implement"])
        for c, rec in zip(h.calls, r["calls"]):
            self.assertTrue(has(c["argv"], OFF if rec["role"] in ("review", "review_fix") else ONE), rec["role"])

    def test_review_and_review_fix_are_off_at_every_level(self):
        for level, impl in (("L4", OFF), ("L5", ONE)):
            h = Harness(verdicts=[("changes_requested", 2)])
            r = h.run(level)
            self.assertEqual([c["role"] for c in r["calls"]], ["implement", "review", "review_fix"])
            self.assertTrue(has(h.calls[0]["argv"], impl))
            self.assertTrue(has(h.calls[1]["argv"], OFF))
            self.assertIn("read-only", h.calls[1]["argv"])
            self.assertTrue(has(h.calls[2]["argv"], OFF))  # the fix turn's text forbids subagents, even at L5
            self.assertEqual([c["subagents"] for c in r["calls"]], [0 if level == "L4" else 1, 0, 0])

    def test_review_only_target_is_off_but_plan_only_is_untouched(self):
        h = Harness()
        h.run("L3", target="review_only")
        self.assertTrue(has(h.calls[0]["argv"], OFF))
        h = Harness()
        r = h.run("L3", target="plan_only")
        self.assertEqual(flags(h.calls[0]["argv"]), [])
        self.assertIsNone(r["calls"][0]["subagents"])

    def test_codex_policy_emits_no_agents_flags_anywhere(self):
        h = Harness(gates=(GATE_BAD, GATE_OK), verdicts=[("changes_requested", 2)])
        r = h.run("L4", policy="codex")
        self.assertEqual([c["role"] for c in r["calls"]], ["implement", "escalate", "review", "review_fix"])
        for c in h.calls:
            self.assertEqual(flags(c["argv"]), [])
        h = Harness()
        h.run("L5", policy="codex")
        self.assertEqual(flags(h.calls[0]["argv"]), [])
        self.assertNotIn(SUBAGENT_HINT, h.calls[0]["argv"][-1])  # the hint only goes with enabled subagents
        self.assertTrue(all(c["subagents"] is None for c in r["calls"]))

    def test_no_flags_without_a_level(self):
        from model_effort_router.flow import run_flow
        h = Harness()
        sp = session_plan(None, (), {"session": Profile("frontier", "high")})
        run_flow(REQ, sp, cwd="/w", runner=h.runner, env={}, gate_fn=h.gate, diff_fn=lambda c: h.diff, emit=h.events.append)
        self.assertEqual(flags(h.calls[0]["argv"]), [])


class ConfigTest(unittest.TestCase):
    def test_default_and_values(self):
        self.assertEqual(resolve_config().subagent_policy, "level")
        for v in ("level", "codex"):
            self.assertEqual(resolve_config(repo={"session": {"subagent_policy": v}}).subagent_policy, v)

    def test_precedence_repo_over_user(self):
        cfg = resolve_config(repo={"session": {"subagent_policy": "codex"}}, user={"session": {"subagent_policy": "level"}})
        self.assertEqual(cfg.subagent_policy, "codex")
        self.assertEqual(resolve_config(user={"session": {"subagent_policy": "codex"}}).subagent_policy, "codex")

    def test_invalid_value_and_section(self):
        for bad in ({"session": {"subagent_policy": "all"}}, {"session": {"subagent_policy": None}}, {"session": []}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                resolve_config(repo=bad)


class CliTest(CliCase):
    def test_dry_run_shows_the_flags_of_the_first_command(self):
        _, out = self.mer("Fix the discount bug in pricing.py", "--dry-run", "--level", "L2")
        self.assertIn("agents.enabled=false", out)
        _, out = self.mer("Fix the discount bug in pricing.py", "--dry-run", "--level", "L5")
        self.assertIn("agents.max_concurrent_threads_per_session=1", out)

    def test_config_switch_reaches_mer_run(self):
        self.assertTrue(has(self.run_and_first_argv(), OFF))
        (self.cwd / ".model-effort-router.json").write_text(
            '{"difficulty": {"backend": "fake"}, "session": {"subagent_policy": "codex"}}')
        self.assertEqual(flags(self.run_and_first_argv()), [])

    def run_and_first_argv(self):
        h = Harness()
        self.mer("Fix the bug in calc.py", h=h)
        return h.calls[0]["argv"]

    def test_chat_has_no_agents_flags(self):
        out = io.StringIO()
        with redirect_stdout(out):
            cli.main(["chat", "--cwd", str(self.cwd), "--dry-run", "--level", "L5", "Fix the bug in calc.py"], env=self.env())
        self.assertNotIn("agents.", out.getvalue())


class LiveRunnerTest(Env):
    def test_policy_merged_into_workdir_config_for_router_runs_only(self):
        (self.fixture / ".model-effort-router.json").write_text('{"gate": {"checks": {"test": "python3 -m unittest"}}}')
        rec = self.run_case("router", subagent_policy="codex")
        cfg = json.loads(self.calls[0]["config"])
        self.assertEqual(cfg["session"], {"subagent_policy": "codex"})
        self.assertEqual(cfg["gate"], {"checks": {"test": "python3 -m unittest"}})  # fixture config kept
        self.assertEqual(rec["subagent_policy"], "codex")
        self.run_case("baseline", events=[], sessions=self.clean_sessions(), subagent_policy="codex")
        self.assertNotIn("session", self.calls[1]["config"])
        self.assertNotIn("subagent", (self.fixture / ".model-effort-router.json").read_text())  # fixture untouched
        self.run_case("router")
        self.assertNotIn("subagent_policy", self.calls[2]["config"])

    def test_policy_alone_creates_config_and_keeps_difficulty_keys(self):
        self.run_case("router", router_backend="jev", router_fallback="subscription", subagent_policy="level")
        cfg = json.loads(self.calls[0]["config"])
        self.assertEqual((cfg["difficulty"]["backend"], cfg["session"]["subagent_policy"]), ("jev", "level"))

    def test_record_carries_the_implement_subagent_cap_mer_reported(self):
        self.mer = {**self.mer, "session_plan": {"implement_subagents": 1}}
        self.assertEqual(self.run_case("router")["implement_subagents"], 1)


if __name__ == "__main__":
    unittest.main()

import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

from model_effort_router import cli
from model_effort_router import review as rv
from model_effort_router.difficulty.subscription import SubscriptionBackend, default_runner
from tests.test_mer_flow import GATE_BAD, GATE_OK, Harness

PROMPT_MARKER = "ZEBRA_PROMPT_MARKER"


class CliCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.cwd = self.root / "repo"
        self.cwd.mkdir()
        (self.cwd / ".model-effort-router.json").write_text('{"difficulty": {"backend": "fake"}}')
        self.state = self.root / "state"
        self.h = Harness()

    def env(self, **spec):
        return {"HOME": str(self.root), "MER_STATE_DIR": str(self.state), "MER_TEST_REGISTRY_MODULE": "tests.fake_registry",
                "MER_TEST_FAKE_BACKEND": json.dumps({"level": "L2", **spec}), "PATH": os.environ["PATH"]}

    def mer(self, request, *flags, spec=None, h=None):
        h = h or self.h
        out = io.StringIO()
        rc = cli.main(["run", "--cwd", str(self.cwd), *flags, request], env=self.env(**(spec or {})), runner=h.runner,
                      gate_fn=h.gate, diff_fn=lambda c: h.diff, out=out)
        return rc, out.getvalue()

    def log_events(self):
        return [json.loads(line) for p in self.state.glob("*.log.jsonl") for line in p.read_text().splitlines()]


class DryRunTest(CliCase):
    def test_l2_dry_run_prints_decision_ladder_and_exact_command_without_running(self):
        rc, out = self.mer("Fix the discount bug in pricing.py", "--dry-run")
        self.assertEqual((rc, self.h.calls, self.state.exists()), (0, [], False))
        for needle in ("level: L2", "session: economy:medium -> gpt-6-luna/medium", "plan first: no", "review: none",
                       "1. balanced:high -> gpt-6-luna/high", "2. frontier:high -> gpt-6.1-sol/high",
                       "first command: codex exec --json --skip-git-repo-check -s workspace-write -m gpt-6-luna"):
            self.assertIn(needle, out)

    def test_l4_auth_dry_run_shows_plan_first_review_and_single_rung(self):
        rc, out = self.mer("Fix the login auth check in auth.py", "--dry-run", spec={"level": "L4"})
        for needle in ("level: L4", "risk flags: auth", "session: frontier:high -> gpt-6.1-sol/high", "plan first: yes",
                       "review: frontier:high", "1. frontier:xhigh", "risk_min:auth"):
            self.assertIn(needle, out)

    def test_review_profile_raises_but_never_lowers_the_review(self):
        _, out = self.mer("review only: check the current diff", "--dry-run", "--review-profile", "frontier:xhigh")
        self.assertIn("review: frontier:xhigh", out)
        _, out = self.mer("Fix the login auth check in auth.py", "--dry-run", "--review-profile", "economy:medium")
        self.assertIn("review: frontier:high", out)  # auth floor kept
        with self.assertRaises(SystemExit) as cm:  # argparse rejects a malformed profile
            self.mer("Fix it", "--dry-run", "--review-profile", "nope")
        self.assertEqual(cm.exception.code, 2)

    def test_dry_run_with_session_override_keeps_risk_plan_first_and_auth_review(self):
        _, out = self.mer("/router session=economy:medium\nFix the login auth check in auth.py", "--dry-run")
        for needle in ("session: economy:medium", "plan first: yes", "review: frontier:high", "override:session"):
            self.assertIn(needle, out)


class DryRunNoModelCallTest(CliCase):
    """A dry run must never spend model quota unless asked (--classify)."""

    def setUp(self):
        super().setUp()
        (self.cwd / ".model-effort-router.json").write_text('{"difficulty": {"backend": "subscription"}}')
        patcher = mock.patch.object(SubscriptionBackend, "classify", side_effect=AssertionError("classifier called"))
        self.classify = patcher.start()
        self.addCleanup(patcher.stop)

    def test_dry_run_refuses_model_classifier_without_level_or_classify(self):
        rc, _ = self.mer("Fix the discount bug in pricing.py", "--dry-run")
        self.assertEqual((rc, self.classify.call_count), (2, 0))

    def test_dry_run_with_level_skips_classifier(self):
        rc, out = self.mer("Fix the login auth check in auth.py", "--dry-run", "--level", "L3")
        self.assertEqual((rc, self.classify.call_count), (0, 0))
        self.assertIn("level: L3 (backend dry-run)", out)
        self.assertIn("risk flags: auth", out)

    def test_dry_run_fails_closed_for_backend_without_calls_model(self):
        (self.cwd / ".model-effort-router.json").write_text('{"difficulty": {"backend": "fake"}}')
        unmarked = mock.Mock(spec=["name", "classify"], side_effect=None)
        unmarked.classify.side_effect = AssertionError("classifier called")
        with mock.patch.object(cli, "_registry", return_value={"fake": lambda: unmarked}):
            rc, _ = self.mer("Fix the discount bug in pricing.py", "--dry-run")
        self.assertEqual((rc, unmarked.classify.call_count), (2, 0))

    def test_level_and_classify_need_dry_run(self):
        for flags in (("--level", "L2"), ("--classify",)):
            rc, _ = self.mer("Fix the bug in calc.py", *flags)
            self.assertEqual((rc, self.h.calls, self.classify.call_count), (2, [], 0))


class RunTest(CliCase):
    def test_json_result_and_exit_zero(self):
        rc, out = self.mer(f"Fix the bug in calc.py {PROMPT_MARKER}", "--json")
        res = json.loads(out)
        self.assertEqual((rc, res["status"], res["level"], res["backend"], res["escalations"]), (0, "ok", "L2", "fake", 0))
        self.assertEqual(res["profile"]["model"], "gpt-6-luna")
        self.assertEqual(res["threads"], ["T-impl"])
        self.assertTrue(res["session_id"].startswith("mer-"))

    def test_human_summary(self):
        rc, out = self.mer("Fix the bug in calc.py")
        self.assertIn("mer: ok (level L2", out)
        self.assertIn("gate: passed", out)
        self.assertIn("implemented", out)

    def test_log_has_the_lifecycle_events_and_no_prompt_text(self):
        h = Harness(gates=(GATE_BAD, GATE_OK))
        self.mer(f"Fix the bug in calc.py {PROMPT_MARKER}", h=h)
        events = self.log_events()
        self.assertEqual([e["event"] for e in events], ["route", "session_start", "gate", "escalate", "gate", "done"])
        route = events[0]
        self.assertEqual((route["decision"]["level"], route["session_plan"]["start"]["tier"], route["source"]),
                         ("L2", "economy", "mer"))
        self.assertIn("prompt_sha", route)
        self.assertNotIn(PROMPT_MARKER, json.dumps(events))
        self.assertEqual(events[-1]["escalations"], 1)

    def test_failed_gate_exit_nonzero_unless_exit_zero(self):
        h = Harness(gates=(GATE_BAD,))
        rc, out = self.mer("Fix the bug in calc.py", h=h)
        self.assertEqual(rc, 1)
        self.assertIn("gate_failed", out)
        self.assertEqual(self.mer("Fix the bug in calc.py", "--exit-zero", h=Harness(gates=(GATE_BAD,)))[0], 0)

    def test_max_escalations_flag(self):
        h = Harness(gates=(GATE_BAD,))
        self.mer("Fix the bug in calc.py", "--max-escalations", "1", h=h)
        self.assertEqual(len(h.calls), 2)

    def test_review_changes_requested_gets_fixed_once(self):
        h = Harness(verdicts=[("changes_requested", 2)])
        rc, out = self.mer("Fix the login auth check in auth.py", "--json", spec={"level": "L4"}, h=h)
        self.assertEqual((rc, json.loads(out)["status"]), (0, "review_fixed"))

    def test_human_summary_shows_door_and_unreviewed_fix(self):
        h = Harness(verdicts=[("changes_requested", 2)])
        rc, out = self.mer("Fix the login auth check in auth.py", spec={"level": "L4"}, h=h)
        self.assertIn("door: two-way; risk flags: auth; blast radius: 2 file(s) in 2 top-level dir(s)", out)
        self.assertIn("review fix applied but not re-reviewed", out)

    def test_explicit_invocation_routes_non_dev_text(self):
        rc, out = self.mer("hello there", "--json")
        self.assertEqual((rc, json.loads(out)["level"]), (0, "L2"))

    def test_plan_only_and_review_only_targets(self):
        _, out = self.mer("write a plan for the parser module", "--json")
        self.assertEqual(json.loads(out)["target"], "plan_only")
        _, out = self.mer("review only: check the parser module changes", "--json")
        self.assertEqual(json.loads(out)["target"], "review_only")

    def test_off_and_rejected_override_run_nothing(self):
        rc, out = self.mer("/router off\nFix the bug in calc.py")
        self.assertEqual((rc, self.h.calls), (0, []))
        self.assertIn("routing is off", out)
        rc, _ = self.mer("/router bogus=1\nFix the bug")
        self.assertEqual((rc, self.h.calls), (2, []))

    def test_manual_mode_needs_session_override(self):
        (self.cwd / ".model-effort-router.json").write_text('{"router": {"mode": "manual"}}')
        self.assertEqual(self.mer("Fix the bug in calc.py")[0], 0)
        self.assertEqual(self.h.calls, [])
        rc, out = self.mer("/router session=frontier:high\nFix the bug in calc.py", "--json")
        self.assertEqual((rc, json.loads(out)["profile"]["model"]), (0, "gpt-6.1-sol"))

    def test_bad_config_is_exit_2(self):
        (self.cwd / ".model-effort-router.json").write_text('{"difficulty": {"backend": "nope"}}')
        self.assertEqual(self.mer("Fix the bug in calc.py")[0], 2)

    def test_negative_max_escalations_rejected(self):
        self.assertEqual(self.mer("Fix the bug in calc.py", "--max-escalations", "-1")[0], 2)


class TerminateTest(CliCase):
    def test_sigterm_during_a_call_exits_143_without_further_calls(self):
        def runner(argv, **kw):
            raise cli.Terminated("SIGTERM")
        rc = cli.main(["run", "--cwd", str(self.cwd), "Fix the bug in calc.py"], env=self.env(), runner=runner,
                      gate_fn=self.h.gate, diff_fn=lambda c: self.h.diff, out=io.StringIO())
        self.assertEqual(rc, 143)

    def test_outer_timeout_also_stops_the_codex_child_group(self):
        """Outer runner -> mer-like child (SIGTERM handler) -> grandchild in its own group: none may survive."""
        pidfile = self.root / "grandchild.pid"
        child = (
            "import signal, subprocess, sys\n"
            "from model_effort_router import cli\n"
            "from model_effort_router.difficulty.subscription import default_runner\n"
            "signal.signal(signal.SIGTERM, cli._raise_terminated)\n"
            "code = 'import os, time; open(os.environ[\"PIDFILE\"], \"w\").write(str(os.getpid())); time.sleep(60)'\n"
            "default_runner([sys.executable, '-c', code], stdin=subprocess.DEVNULL, env=None, timeout_s=60, cwd='.')\n"
        )
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "PIDFILE": str(pidfile)}
        with self.assertRaises(TimeoutError):
            default_runner([sys.executable, "-c", child], stdin=subprocess.DEVNULL, env=env, timeout_s=3,
                           cwd=str(self.root), grace_s=10)
        pid = int(pidfile.read_text())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)
        os.kill(pid, 9)
        self.fail("grandchild survived the outer timeout")


class GitDiffTest(unittest.TestCase):
    def test_not_a_repo_and_repo_with_changes_and_untracked(self):
        with tempfile.TemporaryDirectory() as d:
            d = os.path.realpath(d)
            self.assertEqual(rv.git_diff(d), {"is_repo": False})
            def git(*a):
                return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=d,
                                                        check=True, capture_output=True)
            git("init", "-q")
            Path(d, "a.py").write_text("x = 1\n")
            git("add", "a.py")
            git("commit", "-qm", "init")
            Path(d, "a.py").write_text("x = 2\n")
            Path(d, "new.py").write_text("y = 1\n")
            got = rv.git_diff(d)
            self.assertTrue(got["is_repo"])
            self.assertIn("+x = 2", got["diff"])
            self.assertEqual((got["files"], got["untracked"]), (["a.py"], ["new.py"]))
            self.assertEqual(sorted(os.listdir(d)), [".git", "a.py", "new.py"])  # nothing staged or created


class WrapperTest(unittest.TestCase):
    def test_bin_mer_wrapper_help(self):
        from tests.hook_helpers import PLUGIN, ROOT
        p = subprocess.run(["python3", str(PLUGIN / "bin" / "mer"), "run", "--help"], capture_output=True, text=True, timeout=30,
                           env={**os.environ, "MER_CORE_PATH": str(ROOT)})
        self.assertEqual(p.returncode, 0)
        self.assertIn("--dry-run", p.stdout)
        self.assertTrue(os.access(PLUGIN / "bin" / "mer", os.X_OK))


if __name__ == "__main__":
    unittest.main()


class ChatTest(CliCase):
    def chat(self, request, *flags, spec=None, exec_fn=None):
        out, calls = io.StringIO(), []
        exec_fn = exec_fn or (lambda f, argv, env: calls.append((f, argv, env)))
        rc = cli.main(["chat", "--cwd", str(self.cwd), *flags, request], env=self.env(**(spec or {})),
                      runner=self.h.runner, gate_fn=self.h.gate, diff_fn=lambda c: self.h.diff, out=out, exec_fn=exec_fn)
        return rc, out.getvalue(), calls

    def test_l2_starts_interactive_codex_at_the_routed_profile_with_the_hook_guard(self):
        rc, _, calls = self.chat("Fix the discount bug in pricing.py")
        f, argv, env = calls[0]
        self.assertEqual((rc, f, argv[:3]), (0, "codex", ["codex", "--cd", str(self.cwd)]))
        self.assertEqual(argv[argv.index("-m") + 1], "gpt-6-luna")
        self.assertIn("model_reasoning_effort=medium", argv)
        self.assertNotIn("exec", argv)  # interactive, not `codex exec`
        self.assertEqual((argv[-1], env["MER_CLASSIFIER"]), ("Fix the discount bug in pricing.py", "1"))
        self.assertEqual(self.h.calls, [])  # no gate/escalation/review session
        self.assertEqual([e["source"] for e in self.log_events()], ["mer chat"])

    def test_auth_work_gets_plan_first_and_review_hint(self):
        rc, out, calls = self.chat("Fix the login auth check in auth.py", "--dry-run", spec={"level": "L3"})
        self.assertEqual(calls, [])
        self.assertIn("gpt-6-luna -c model_reasoning_effort=high", out)
        self.assertIn("short plan", out)

    def test_plan_only_is_read_only(self):
        _, out, _ = self.chat("plan only: how should we add caching to pricing.py?", "--dry-run")
        self.assertIn("-s read-only", out)

    def test_off_starts_plain_codex(self):
        _, _, calls = self.chat("/router off\nFix the bug in calc.py")
        self.assertEqual(calls[0][1], ["codex", "--cd", str(self.cwd), "Fix the bug in calc.py"])

    def test_missing_codex_is_reported(self):
        def boom(f, argv, env):
            raise FileNotFoundError("codex")
        self.assertEqual(self.chat("Fix the bug in calc.py", exec_fn=boom)[0], 127)

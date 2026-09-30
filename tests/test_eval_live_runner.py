import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from evaluation import live_runner as lr

FIX = Path(__file__).resolve().parent / "fixtures"
ROOT = "01a0f40a-7449-7100-bb6b-978b137bb996"
STREAM = (FIX / "exec_router.jsonl").read_text()


ROUTE = {"event": "route", "decision": {"backend": "subscription", "level": "L2"},
         "classifier_usage": {"input_tokens": 29757, "cached_input_tokens": 6912, "output_tokens": 20,
                              "reasoning_output_tokens": 0}}
SPAWN = {"event": "stage_spawn", "stage": "implement", "decision": "allow", "fix_count": 0}
GOOD_EVENTS = [ROUTE, SPAWN, {"event": "stage_spawn", "stage": "implement", "decision": "allow", "fix_count": 1},
               {"event": "review", "verdict": "changes_requested", "findings": 5},
               {"event": "review", "verdict": "approved", "findings": 2}]


def case(id="c1", task="Fix the bug in calc.py", target="route", level="L2"):
    lab = lambda who: {"labeler": who, "level": level, "risk_flags": [], "target": target}
    return {"id": id, "task": task, "paths": [], "status": "adjudicated", "labels": [lab("a"), lab("b")],
            "final": {"level": level, "risk_flags": [], "target": target}}


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.fixture = self.root / "fixture"
        (self.fixture / ".codex").mkdir(parents=True)
        (self.fixture / ".codex" / "hooks.json").write_text("{}")
        (self.fixture / "calc.py").write_text("x = 1\n")
        self.workdir = self.root / "work"
        self.sessions = self.root / "sessions"
        self.sessions.mkdir()
        for f in (FIX / "rollouts").glob("*.jsonl"):
            shutil.copy(f, self.sessions / f.name)
        self.calls = []
        self.fail_first = False

    def runner(self, cmd, *, stdin, env, timeout_s, cwd, log_events=()):
        self.calls.append({"cmd": cmd, "env": env, "cwd": cwd, "timeout_s": timeout_s,
                           "had_hooks": (Path(cwd) / ".codex").exists(),
                           "stale": (Path(cwd) / "stale.txt").exists()})
        if self.fail_first and len(self.calls) == 1:
            raise TimeoutError("slow")
        if log_events:
            Path(env["MER_STATE_DIR"]).mkdir(parents=True, exist_ok=True)
            (Path(env["MER_STATE_DIR"]) / "s.log.jsonl").write_text("\n".join(map(json.dumps, log_events)))
        (Path(cwd) / "calc.py").write_text("x = 2\n")  # the run edits its own copy
        (Path(cwd) / "stale.txt").write_text("left over")
        for f in self.sessions.glob("*.jsonl"):  # rollouts written during the run
            os.utime(f, None)
        return STREAM

    def run_case(self, mode, events=GOOD_EVENTS, sessions=None, **kw):
        return lr.run_case(case(), mode, self.fixture, workdir=self.workdir,
                           runner=lambda *a, **k: self.runner(*a, log_events=events, **k),
                           sessions_dir=sessions or self.sessions, gate_fn=lambda cwd: "passed", **kw)

    def clean_sessions(self):
        d = self.root / "clean"
        d.mkdir()
        shutil.copy(FIX / "rollouts" / "rollout-main.jsonl", d)
        return d


class CommandTest(unittest.TestCase):
    def test_build_command(self):
        cmd = lr.build_command("do it", "/w/x", model="gpt-6-luna", effort="high")
        self.assertEqual(cmd[:3], ["codex", "exec", "--json"])
        self.assertIn("--skip-git-repo-check", cmd)
        self.assertEqual(cmd[cmd.index("-m") + 1], "gpt-6-luna")
        self.assertIn("model_reasoning_effort=high", cmd)
        self.assertIn('projects."/w/x".trust_level="trusted"', cmd)
        self.assertEqual(cmd[-1], "do it")
        self.assertFalse([c for c in cmd if "bypass" in c])

    def test_model_and_effort_optional(self):
        cmd = lr.build_command("p", "/w")
        self.assertNotIn("-m", cmd)
        self.assertFalse([c for c in cmd if c.startswith("model_reasoning_effort")])

    def test_env_baseline_disables_router_hooks_router_does_not(self):
        base = lr.build_env("baseline", "/s", {"A": "1"})
        self.assertEqual((base["MER_CLASSIFIER"], base["MER_STATE_DIR"], base["A"]), ("1", "/s", "1"))
        self.assertNotIn("MER_CLASSIFIER", lr.build_env("router", "/s", {}))

    def test_read_events_roundtrip_and_skips_bad_lines(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "l.jsonl"
            p.write_text('{"event":"a"}\nnot json\n{"event":"b"}\n')
            self.assertEqual([e["event"] for e in lr.read_events(p)], ["a", "b"])
            self.assertEqual(lr.read_events(Path(d) / "missing"), [])


class RunCaseTest(Env):
    def test_router_record_sums_main_subagents_and_measured_classifier(self):
        rec = self.run_case("router")
        self.assertEqual((rec["case_id"], rec["mode"], rec["fix_rounds"], rec["review_verdict"],
                          rec["review_findings"]), ("c1", "router", 1, "approved", 2))
        self.assertEqual(rec["gate_overall"], "passed")
        self.assertIsNone(rec["requirements_met"])
        self.assertTrue(rec["router_active"])
        u = rec["usage"]
        self.assertEqual(u["classifier"], {"input": 29757, "cached_input": 6912, "output": 20, "reasoning_output": 0})
        self.assertNotIn("classifier_estimated", u)
        self.assertEqual(u["incomplete_reasons"], [])
        self.assertEqual(set(u["stages"]), {"plan", "implement", "review"})
        self.assertEqual(u["total"], (384934 + 1085) + (29757 + 20) + (45000 + 900) + (60000 + 3000) + (30000 + 700))

    def test_router_inactive_without_route_or_without_stage_spawn(self):
        self.assertFalse(self.run_case("router", events=[ROUTE])["router_active"])
        self.assertFalse(self.run_case("router", events=[SPAWN])["router_active"])
        self.assertFalse(self.run_case("router", events=[])["router_active"])

    def test_route_event_without_classifier_usage_key_means_no_model_call_not_missing(self):
        rec = self.run_case("router", events=[{"event": "route", "decision": {"backend": "rules"}}, SPAWN])
        self.assertIsNone(rec["usage"]["classifier"])
        self.assertEqual(rec["usage"]["incomplete_reasons"], [])

    def test_explicit_null_classifier_usage_marks_run_incomplete_never_estimated(self):
        rec = self.run_case("router", events=[{"event": "route", "decision": {"backend": "subscription"},
                                               "classifier_usage": None}, SPAWN])
        self.assertIsNone(rec["usage"]["classifier"])
        self.assertIn("classifier_usage_missing", rec["usage"]["incomplete_reasons"])

    def test_classifier_usage_summed_over_multiple_route_events(self):
        rec = self.run_case("router", events=[ROUTE, ROUTE, SPAWN])
        self.assertEqual(rec["usage"]["classifier"]["input"], 2 * 29757)

    def test_baseline_clean_when_no_router_activity(self):
        rec = self.run_case("baseline", events=[], sessions=self.clean_sessions())
        self.assertFalse(self.calls[0]["had_hooks"])
        self.assertEqual(self.calls[0]["env"]["MER_CLASSIFIER"], "1")
        self.assertEqual((rec["fix_rounds"], rec["review_verdict"], rec["usage"]["classifier"],
                          rec["contaminated"]), (0, None, None, False))
        self.assertNotIn("router_active", rec)

    def test_baseline_contaminated_by_mer_subagent_or_route_event(self):
        self.assertTrue(self.run_case("baseline", events=[])["contaminated"])  # sessions hold mer-* rollouts
        self.assertTrue(self.run_case("baseline", events=[ROUTE], sessions=self.clean_sessions())["contaminated"])

    def test_fixed_workdir_is_reset_between_runs_and_realpathed(self):
        self.run_case("router")
        self.run_case("router")
        self.assertEqual(self.calls[0]["cwd"], os.path.realpath(self.workdir))
        self.assertEqual([c["cwd"] for c in self.calls], [self.calls[0]["cwd"]] * 2)
        self.assertEqual([c["stale"] for c in self.calls], [False, False])
        self.assertTrue(self.calls[1]["had_hooks"])
        self.assertIn(f'projects."{self.calls[0]["cwd"]}".trust_level', " ".join(self.calls[0]["cmd"]))

    def test_workdir_through_symlink_uses_real_path(self):
        link = self.root / "link"
        link.symlink_to(self.root)
        lr.run_case(case(), "router", self.fixture, workdir=link / "work2",
                    runner=lambda *a, **k: self.runner(*a, **k), sessions_dir=self.sessions,
                    gate_fn=lambda cwd: "passed")
        self.assertEqual(self.calls[0]["cwd"], str(self.root / "work2"))

    def test_fixture_untouched_and_workdir_cleared_afterwards(self):
        self.run_case("router")
        self.assertEqual((self.fixture / "calc.py").read_text(), "x = 1\n")
        self.assertEqual(os.listdir(self.workdir), [lr.MARKER])  # contents cleared, marker kept

    def test_runner_error_becomes_error_record_and_workdir_cleared(self):
        self.fail_first = True
        rec = self.run_case("router")
        self.assertTrue(rec["error"].startswith("TimeoutError"))
        self.assertEqual(rec["gate_overall"], "incomplete")
        self.assertIn("run_error", rec["usage"]["incomplete_reasons"])
        self.assertEqual(os.listdir(self.workdir), [lr.MARKER])
        from evaluation import baseline
        baseline.validate_record(rec)

    def test_marked_workdir_is_reset(self):
        self.workdir.mkdir()
        (self.workdir / lr.MARKER).write_text("")
        (self.workdir / "stale.txt").write_text("old")
        (self.workdir / "sub").mkdir()
        self.run_case("router")
        self.assertFalse(self.calls[0]["stale"])
        self.assertTrue((self.workdir / lr.MARKER).exists())

    def test_created_workdir_gets_marker(self):
        self.run_case("router")
        self.assertTrue((self.workdir / lr.MARKER).exists())

    def refused(self, workdir, needle, **kw):
        with self.assertRaises(lr.WorkdirError) as cm:
            lr.run_case(case(), "router", self.fixture, workdir=workdir, runner=self.runner,
                        sessions_dir=self.sessions, gate_fn=lambda cwd: "passed", **kw)
        self.assertIn(needle, str(cm.exception))
        self.assertEqual(self.calls, [])
        self.assertEqual((self.fixture / "calc.py").read_text(), "x = 1\n")

    def test_refuses_existing_unmarked_dir_and_deletes_nothing(self):
        self.workdir.mkdir()
        (self.workdir / "precious.txt").write_text("keep")
        self.refused(self.workdir, "marker")
        self.assertEqual((self.workdir / "precious.txt").read_text(), "keep")

    def test_refuses_fixture_itself_inside_fixture_and_parent_of_fixture_even_if_marked(self):
        (self.fixture / lr.MARKER).write_text("")
        self.refused(self.fixture, "fixture")
        sub = self.fixture / "sub"
        sub.mkdir()
        (sub / lr.MARKER).write_text("")
        self.refused(sub, "fixture")
        (self.root / lr.MARKER).write_text("")
        self.refused(self.root, "fixture")

    def test_refuses_cwd_home_and_filesystem_root_even_if_marked(self):
        marked = self.root / "m"
        marked.mkdir()
        (marked / lr.MARKER).write_text("")
        with mock.patch("os.getcwd", return_value=str(marked)):
            self.refused(marked, "current directory")
        with mock.patch.dict(os.environ, {"HOME": str(marked)}):
            self.refused(marked, "home")
        self.refused("/", "root")

    def test_refuses_workdir_that_contains_cwd(self):
        marked = self.root / "m"
        (marked / "deep").mkdir(parents=True)
        (marked / lr.MARKER).write_text("")
        with mock.patch("os.getcwd", return_value=str(marked / "deep")):
            self.refused(marked, "current directory")

    def test_record_is_valid_for_baseline_module(self):
        from evaluation import baseline
        baseline.validate_record(self.run_case("router"))


class CliTest(Env):
    def setUp(self):
        super().setUp()
        self.corpus = self.root / "c.jsonl"
        rows = [case("a"), case("b", target="plan_only"), case("d", task="what is x", target="no_route", level=None)]
        self.corpus.write_text("\n".join(json.dumps(r) for r in rows))
        self.out = self.root / "runs.jsonl"

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = lr.main(list(argv), runner=lambda *a, **k: self.runner(*a, log_events=GOOD_EVENTS, **k),
                         sessions_dir=self.sessions, gate_fn=lambda cwd: "passed")
        self.err = err.getvalue()
        return rc, out.getvalue()

    def base_args(self):
        return ["--cases", str(self.corpus), "--fixture", str(self.fixture), "--out", str(self.out),
                "--workdir", str(self.workdir)]

    def test_without_live_nothing_runs_and_plan_is_printed(self):
        rc, out = self.cli(*self.base_args())
        self.assertEqual((rc, self.calls, self.out.exists()), (0, [], False))
        self.assertIn("--live", out)
        self.assertIn("dry-run", out)
        self.assertIn('"codex"', out.replace("'", '"'))

    def test_live_runs_only_route_cases_in_both_modes_and_appends_records(self):
        rc, _ = self.cli(*self.base_args(), "--live")
        self.assertEqual(rc, 0)
        recs = [json.loads(l) for l in self.out.read_text().splitlines()]
        self.assertEqual([(r["case_id"], r["mode"]) for r in recs],
                         [("a", "baseline"), ("a", "router")])
        self.assertEqual(len(self.calls), 2)

    def test_live_banner_states_preconditions_and_trust_side_effect(self):
        self.cli(*self.base_args(), "--live")
        for needle in ("subscription usage", "plugin", "trust", "trust_level", "config.toml", "installed globally"):
            self.assertIn(needle, self.err)
        self.assertNotIn("bypass", self.err.replace("does not use", ""))

    def test_dry_run_prints_no_banner_and_runs_nothing(self):
        self.cli(*self.base_args())
        self.assertEqual((self.err, self.calls), ("", []))

    def test_unsafe_workdir_exits_nonzero_before_anything_runs_even_in_dry_run(self):
        self.workdir.mkdir()
        (self.workdir / "precious.txt").write_text("keep")
        for extra in ([], ["--live"]):
            self.assertEqual(self.cli(*self.base_args(), *extra)[0], 1)
            self.assertIn("marker", self.err)
        self.assertEqual((self.calls, (self.workdir / "precious.txt").read_text()), ([], "keep"))

    def test_dry_run_prints_real_workdir_not_placeholder(self):
        _, out = self.cli(*self.base_args())
        self.assertIn(os.path.realpath(self.workdir), out)
        self.assertNotIn("temp-copy", out)

    def test_one_failing_case_does_not_stop_the_batch(self):
        self.fail_first = True
        self.assertEqual(self.cli(*self.base_args(), "--live")[0], 0)
        recs = [json.loads(l) for l in self.out.read_text().splitlines()]
        self.assertEqual(len(recs), 2)
        self.assertIn("error", recs[0])
        self.assertNotIn("error", recs[1])

    def test_limit_and_missing_fixture(self):
        self.assertEqual(self.cli(*self.base_args(), "--live", "--limit", "0")[0], 1)
        bad = self.base_args()
        bad[3] = str(self.root / "nope")
        self.assertEqual(self.cli(*bad, "--live")[0], 1)


if __name__ == "__main__":
    unittest.main()

import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from evaluation import live_runner as lr

FIX = Path(__file__).resolve().parent / "fixtures"
ROOT = "01a0f40a-7449-7100-bb6b-978b137bb996"
STREAM = (FIX / "exec_router.jsonl").read_text()


REV = "01a0f40a-0000-7000-8000-00000000aaaa"  # mer's independent review session (a separate root session)
LONE = "01a0f40a-0000-7000-8000-00000000bbbb"  # a mer thread whose rollout is not on disk
ROUTE = {"event": "route", "decision": {"backend": "subscription", "level": "L2"},
         "classifier_usage": {"input_tokens": 29757, "cached_input_tokens": 6912, "output_tokens": 20,
                              "reasoning_output_tokens": 0}}
START = {"event": "session_start", "role": "implement", "thread_id": ROOT}
GOOD_EVENTS = [ROUTE, START, {"event": "gate", "overall": "failed"}, {"event": "escalate", "index": 1},
               {"event": "review", "verdict": "approved", "findings": 2}, {"event": "done", "exit_code": 0}]
PROF = {"tier": "economy", "model": "gpt-6-luna", "requested_effort": "medium", "applied_effort": "medium"}
MER = {"status": "ok", "exit_code": 0, "level": "L2", "escalations": 1, "profile": PROF,
       "final_profile": {**PROF, "tier": "balanced", "applied_effort": "high"},
       "review": {"verdict": "approved", "findings": 2, "skipped": None}, "threads": [ROOT, REV],
       "calls": [{"role": "implement", "thread_id": ROOT, "usage": {"input": 100, "cached_input": 0, "output": 10, "reasoning_output": 0}}]}


def case(id="c1", task="Fix the bug in calc.py", target="route", level="L2"):
    lab = lambda who: {"labeler": who, "level": level, "risk_flags": [], "target": target}
    return {"id": id, "task": task, "paths": [], "status": "adjudicated", "labels": [lab("a"), lab("b")],
            "final": {"level": level, "risk_flags": [], "target": target}}


def claude_result(sid="CS1", text="done", i=10, created=20, read=300, o=5, cost=0.0123):
    return json.dumps({"type": "result", "subtype": "success", "is_error": False, "session_id": sid, "result": text,
                       "usage": {"input_tokens": i, "cache_creation_input_tokens": created, "cache_read_input_tokens": read,
                                 "output_tokens": o}, "total_cost_usd": cost})


CLAUDE_RESULT = claude_result()


def write_rollout(directory, thread, i, o):
    lines = [{"type": "session_meta", "payload": {"id": thread, "session_id": thread, "thread_source": "user"}},
             {"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {
                 "input_tokens": i, "cached_input_tokens": 0, "output_tokens": o, "reasoning_output_tokens": 0}}}}]
    (Path(directory) / f"rollout-{thread}.jsonl").write_text("\n".join(map(json.dumps, lines)))


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
        self.mer = MER
        self.claude = CLAUDE_RESULT

    def runner(self, cmd, *, stdin, env, timeout_s, cwd, grace_s=None, log_events=()):
        git = subprocess.run(["git", "log", "--oneline"], cwd=cwd, capture_output=True, text=True)
        self.calls.append({"cmd": cmd, "env": env, "cwd": cwd, "timeout_s": timeout_s, "grace_s": grace_s,
                           "had_hooks": (Path(cwd) / ".codex").exists(), "had_claude": (Path(cwd) / ".claude").exists(), "stale": (Path(cwd) / "stale.txt").exists(),
                           "commits": len(git.stdout.splitlines()) if git.returncode == 0 else None,
                           "config": (Path(cwd) / ".model-effort-router.json").read_text()
                           if (Path(cwd) / ".model-effort-router.json").exists() else None})
        if self.fail_first and len(self.calls) == 1:
            raise TimeoutError("slow")
        if log_events:
            Path(env["MER_STATE_DIR"]).mkdir(parents=True, exist_ok=True)
            (Path(env["MER_STATE_DIR"]) / "s.log.jsonl").write_text("\n".join(map(json.dumps, log_events)))
        (Path(cwd) / "calc.py").write_text("x = 2\n")  # the run edits its own copy
        (Path(cwd) / "new.py").write_text("y = 1\n")
        (Path(cwd) / "__pycache__").mkdir(exist_ok=True)
        (Path(cwd) / "__pycache__" / "calc.cpython-311.pyc").write_bytes(b"\x00bytecode")
        (Path(cwd) / "stale.txt").write_text("left over")
        for f in self.root.rglob("rollout-*.jsonl"):  # rollouts written during the run
            os.utime(f, None)
        return STREAM if cmd[0] == "codex" else self.claude if cmd[0] == "claude" else json.dumps(self.mer)

    def run_case(self, mode, events=GOOD_EVENTS, sessions=None, **kw):
        kw.setdefault("out_dir", self.root / "out")
        return lr.run_case(case(), mode, self.fixture, workdir=self.workdir,
                           runner=lambda *a, **k: self.runner(*a, log_events=events, **k),
                           sessions_dir=sessions or self.router_sessions(), gate_fn=lambda cwd: "passed", **kw)

    def router_sessions(self):
        """Only mer's own root sessions: the implement thread (fixture main) and its review thread."""
        d = self.root / "router-sessions"
        if not d.exists():
            d.mkdir()
            shutil.copy(FIX / "rollouts" / "rollout-main.jsonl", d)
            write_rollout(d, REV, 50000, 700)
        return d

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
        router = lr.build_env("router", "/s", {})
        self.assertNotIn("MER_CLASSIFIER", router)  # mer sets the guard itself for the sessions it starts
        self.assertTrue(os.path.isdir(os.path.join(router["PYTHONPATH"], "model_effort_router")))

    def test_env_pins_the_codex_host_in_both_modes(self):
        for mode in ("baseline", "router"):
            self.assertEqual(lr.build_env(mode, "/s", {"MER_HOST": "claude"})["MER_HOST"], "codex")

    def test_build_mer_command(self):
        cmd = lr.build_mer_command("do it", "/w/x")
        self.assertEqual(cmd[1:4], ["-m", "model_effort_router.cli", "run"])
        self.assertEqual(cmd[cmd.index("--cwd") + 1], "/w/x")
        for flag in ("--json", "--exit-zero"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[-1], "do it")
        self.assertEqual(cmd[cmd.index("--timeout") + 1], "1200")  # per call, passed explicitly
        self.assertFalse([c for c in cmd if "live" in c or "bypass" in c])

    def test_read_events_roundtrip_and_skips_bad_lines(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "l.jsonl"
            p.write_text('{"event":"a"}\nnot json\n{"event":"b"}\n')
            self.assertEqual([e["event"] for e in lr.read_events(p)], ["a", "b"])
            self.assertEqual(lr.read_events(Path(d) / "missing"), [])


class RunCaseTest(Env):
    def test_router_runs_the_mer_cli_not_codex_exec(self):
        self.run_case("router")
        cmd = self.calls[0]["cmd"]
        self.assertNotEqual(cmd[0], "codex")
        self.assertIn("model_effort_router.cli", cmd)
        self.assertEqual(cmd[-1], "Fix the bug in calc.py")
        self.assertNotIn("MER_CLASSIFIER", self.calls[0]["env"])
        # outer timeout covers every mer call; SIGTERM grace lets mer stop its own codex call first
        self.assertEqual((self.calls[0]["timeout_s"], self.calls[0]["grace_s"]),
                         (lr.DEFAULT_TIMEOUT_S * lr.MER_CALL_BUDGET + lr.MER_GATE_BUDGET_S, lr.MER_GRACE_S))

    def test_router_record_carries_mer_outcome_and_sums_threads_from_rollouts(self):
        rec = self.run_case("router")
        self.assertEqual((rec["case_id"], rec["mode"], rec["fix_rounds"], rec["review_verdict"],
                          rec["review_findings"], rec["escalations"]), ("c1", "router", 1, "approved", 2, 1))
        self.assertEqual((rec["level"], rec["thread_ids"]), ("L2", [ROOT, REV]))
        self.assertEqual(rec["session_profile"], PROF)
        self.assertEqual(rec["final_profile"]["model"], "gpt-6-luna")
        self.assertEqual((rec["model"], rec["effort"]), ("gpt-6-luna", "medium"))
        self.assertEqual(rec["gate_overall"], "passed")
        self.assertIsNone(rec["requirements_met"])
        self.assertTrue(rec["router_active"])
        u = rec["usage"]
        self.assertEqual(u["classifier"], {"input": 29757, "cached_input": 6912, "output": 20, "reasoning_output": 0})
        self.assertEqual(u["incomplete_reasons"], [])
        self.assertEqual(u["stages"], {})
        # implement session total from its (cumulative) rollout once, plus the separate review root session
        self.assertEqual(u["total"], (384934 + 1085) + (50000 + 700) + (29757 + 20))

    def test_thread_without_rollout_falls_back_to_mer_reported_usage_once(self):
        usage = {"input": 100, "cached_input": 0, "output": 10, "reasoning_output": 0}
        self.mer = {**MER, "threads": [ROOT, LONE], "calls": [
            {"role": "implement", "thread_id": LONE, "usage": usage}, {"role": "escalate", "thread_id": LONE, "usage": usage},
            {"role": "implement", "thread_id": ROOT, "usage": usage}]}
        rec = self.run_case("router")
        self.assertEqual(rec["usage"]["total"], (384934 + 1085) + 220 + (29757 + 20))

    def test_rollout_without_token_count_falls_back_to_mer_reported_usage(self):
        d = self.root / "no-usage"
        d.mkdir()
        shutil.copy(FIX / "rollouts" / "rollout-main.jsonl", d)
        meta = {"type": "session_meta", "payload": {"id": LONE, "session_id": LONE, "thread_source": "user"}}
        (d / f"rollout-{LONE}.jsonl").write_text(json.dumps(meta))
        usage = {"input": 100, "cached_input": 0, "output": 10, "reasoning_output": 0}
        self.mer = {**MER, "threads": [ROOT, LONE], "calls": [{"role": "review", "thread_id": LONE, "usage": usage}]}
        rec = self.run_case("router", sessions=d)
        self.assertEqual(rec["usage"]["total"], (384934 + 1085) + 110 + (29757 + 20))

    def test_mer_exit_nonzero_status_is_recorded_not_an_error(self):
        self.mer = {**MER, "status": "gate_failed", "exit_code": 1}
        rec = self.run_case("router")
        self.assertNotIn("error", rec)
        self.assertEqual(rec["mer_status"], "gate_failed")

    def test_unparseable_mer_output_is_an_error_record(self):
        self.mer = "oops"
        self.assertIn("error", self.run_case("router"))

    def test_record_for_baseline_carries_model_and_effort(self):
        rec = self.run_case("baseline", events=[], sessions=self.clean_sessions(), model="m", effort="low")
        self.assertEqual((rec["model"], rec["effort"], rec["thread_ids"]), ("m", "low", [ROOT]))

    def test_router_inactive_without_route_or_without_session_start(self):
        self.assertFalse(self.run_case("router", events=[ROUTE])["router_active"])
        self.assertFalse(self.run_case("router", events=[START])["router_active"])
        self.assertFalse(self.run_case("router", events=[])["router_active"])

    def test_route_event_without_classifier_usage_key_means_no_model_call_not_missing(self):
        rec = self.run_case("router", events=[{"event": "route", "decision": {"backend": "rules"}}, START])
        self.assertIsNone(rec["usage"]["classifier"])
        self.assertEqual(rec["usage"]["incomplete_reasons"], [])

    def test_explicit_null_classifier_usage_marks_run_incomplete_never_estimated(self):
        rec = self.run_case("router", events=[{"event": "route", "decision": {"backend": "subscription"},
                                               "classifier_usage": None}, START])
        self.assertIsNone(rec["usage"]["classifier"])
        self.assertIn("classifier_usage_missing", rec["usage"]["incomplete_reasons"])

    def test_classifier_usage_summed_over_multiple_route_events(self):
        rec = self.run_case("router", events=[ROUTE, ROUTE, START])
        self.assertEqual(rec["usage"]["classifier"]["input"], 2 * 29757)

    def test_workdir_is_a_git_repo_with_one_fixture_commit_before_the_run(self):
        self.run_case("router")
        self.assertEqual(self.calls[0]["commits"], 1)
        self.assertEqual(self.workdir.parent, self.root)  # git init only inside the eval workdir
        self.assertFalse((self.fixture / ".git").exists())

    def test_diff_saved_per_case_and_mode_with_untracked_list(self):
        rec = self.run_case("router")
        path = Path(rec["diff_path"])
        self.assertEqual(path, self.root / "out" / "c1.router.r1.diff")
        text = path.read_text()
        self.assertIn("+x = 2", text)
        self.assertIn("new.py", text.split("diff --git")[0])  # untracked list header
        self.assertIn("+y = 1", text)
        self.assertNotIn(lr.MARKER, text)
        self.assertNotIn("__pycache__", text)  # bytecode from test runs never reaches the saved diff
        self.assertEqual(Path(self.run_case("baseline", events=[], sessions=self.clean_sessions())["diff_path"]).name,
                         "c1.baseline.r1.diff")

    def test_jev_usage_without_cached_field_is_counted_exactly(self):
        jev = {"event": "route", "decision": {"backend": "jev", "level": "L2"},
               "classifier_usage": {"input_tokens": 541, "cached_input_tokens": 0, "output_tokens": 12,
                                    "reasoning_output_tokens": 0}}
        bare = {**jev, "classifier_usage": {"input_tokens": 541, "output_tokens": 12}}  # as Jev reports it
        for event in (jev, bare):
            rec = self.run_case("router", events=[event, START])
            self.assertEqual(rec["usage"]["classifier"], {"input": 541, "cached_input": 0, "output": 12, "reasoning_output": 0})
            self.assertEqual(rec["usage"]["total"], (384934 + 1085) + (50000 + 700) + 553)
            self.assertEqual(rec["usage"]["incomplete_reasons"], [])

    def test_record_shows_classifier_backend_used_and_fallback_cause(self):
        jev = {"event": "route", "decision": {"backend": "jev", "level": "L2", "reason_codes": []}, "fallback": False}
        self.assertEqual(self.run_case("router", events=[jev, START])["classifier_backend"], "jev")
        fell = {"event": "route", "fallback": True, "decision": {"backend": "subscription", "level": "L2",
                "reason_codes": ["x", "fallback_cause:jev:TimeoutError"]}}
        rec = self.run_case("router", events=[fell, START])
        self.assertEqual((rec["classifier_backend"], rec["classifier_fallback"], rec["classifier_fallback_causes"]),
                         ("subscription", True, ["jev:TimeoutError"]))
        dflt = {"event": "route", "fallback": True, "decision": {"backend": "default",
                "reason_codes": ["jev:TimeoutError", "subscription:RuntimeError"]}}
        self.assertEqual(self.run_case("router", events=[dflt, START])["classifier_fallback_causes"],
                         ["jev:TimeoutError", "subscription:RuntimeError"])
        self.assertEqual(self.run_case("router", events=[])["classifier_backend"], None)

    def test_router_backend_merged_into_workdir_config_only_for_router_runs(self):
        (self.fixture / ".model-effort-router.json").write_text(
            '{"gate": {"checks": {"test": "python3 -m unittest"}}, "difficulty": {"timeout_s": 7}}')
        self.run_case("router", router_backend="jev", router_fallback="subscription")
        cfg = json.loads(self.calls[0]["config"])
        self.assertEqual(cfg["gate"], {"checks": {"test": "python3 -m unittest"}})
        self.assertEqual(cfg["difficulty"], {"timeout_s": 7, "backend": "jev", "fallback": "subscription"})
        self.run_case("baseline", events=[], sessions=self.clean_sessions(), router_backend="jev")
        self.assertIn("python3 -m unittest", self.calls[1]["config"])
        self.assertNotIn("jev", self.calls[1]["config"])
        self.assertNotIn("jev", (self.fixture / ".model-effort-router.json").read_text())  # fixture untouched
        self.run_case("router")
        self.assertNotIn("jev", self.calls[2]["config"])  # no option: config as the fixture has it

    def test_router_backend_creates_config_when_fixture_has_none(self):
        self.run_case("router", router_backend="jev", router_fallback="subscription")
        self.assertEqual(json.loads(self.calls[0]["config"])["difficulty"], {"backend": "jev", "fallback": "subscription"})

    def test_no_out_dir_means_no_diff_file(self):
        self.assertIsNone(self.run_case("router", out_dir=None)["diff_path"])

    def test_baseline_clean_when_no_router_activity(self):
        rec = self.run_case("baseline", events=[], sessions=self.clean_sessions())
        self.assertFalse(self.calls[0]["had_hooks"])
        self.assertEqual(self.calls[0]["cmd"][0], "codex")
        self.assertEqual(self.calls[0]["env"]["MER_CLASSIFIER"], "1")
        self.assertEqual((rec["fix_rounds"], rec["review_verdict"], rec["usage"]["classifier"],
                          rec["contaminated"]), (0, None, None, False))
        self.assertNotIn("router_active", rec)

    def test_baseline_contaminated_by_mer_subagent_or_route_event(self):
        self.assertTrue(self.run_case("baseline", events=[], sessions=self.sessions)["contaminated"])  # mer-* rollouts
        self.assertTrue(self.run_case("baseline", events=[ROUTE], sessions=self.clean_sessions())["contaminated"])

    def test_fixed_workdir_is_reset_between_runs_and_realpathed(self):
        self.run_case("router")
        self.run_case("router")
        self.assertEqual(self.calls[0]["cwd"], os.path.realpath(self.workdir))
        self.assertEqual([c["cwd"] for c in self.calls], [self.calls[0]["cwd"]] * 2)
        self.assertEqual([c["stale"] for c in self.calls], [False, False])
        self.assertTrue(self.calls[1]["had_hooks"])
        self.run_case("baseline", events=[], sessions=self.clean_sessions())
        self.assertIn(f'projects."{self.calls[0]["cwd"]}".trust_level', " ".join(self.calls[2]["cmd"]))

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

    def test_refuses_workdir_inside_a_git_work_tree(self):
        outer = self.root / "outer"
        (outer / ".git").mkdir(parents=True)
        self.refused(outer / "wd", "git work tree")

    def test_git_never_falls_through_when_the_run_deletes_dot_git(self):
        outer = self.root / "outer"
        outer.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=outer, check=True)
        repo = outer / "wd"
        repo.mkdir()
        lr.init_git_repo(str(repo))
        shutil.rmtree(repo / ".git")
        (repo / "new.txt").write_text("x")
        with self.assertRaises(subprocess.CalledProcessError):
            lr.save_diff(str(repo), str(self.root / "out.diff"))
        self.assertEqual(subprocess.run(["git", "status", "--porcelain"], cwd=outer, capture_output=True,
                                        text=True).stdout, "?? wd/\n")  # outer index untouched

    def test_record_is_valid_for_baseline_module(self):
        from evaluation import baseline
        baseline.validate_record(self.run_case("router"))


class ClaudeHostTest(Env):
    """--host claude: no rollouts (~/.codex/sessions is never read), usage and cost come from the results."""

    def run_claude(self, mode, **kw):
        kw.setdefault("events", [ROUTE, START] if mode == "router" else [])
        return self.run_case(mode, sessions=self.root / "no-such-sessions", host="claude", **kw)

    def test_baseline_command_has_the_prompt_after_dashes_and_keeps_the_agent_tool(self):
        cmd = lr.build_command("do it", "/w", host="claude")
        self.assertEqual(cmd, ["claude", "-p", "--output-format", "json", "--permission-mode", "auto", "--", "do it"])
        cmd = lr.build_command("--model evil", "/w", "m", "high", host="claude")
        self.assertEqual(cmd[-4:], ["--effort", "high", "--", "--model evil"])
        self.assertEqual(cmd[cmd.index("--model") + 1], "m")
        self.assertFalse([c for c in cmd if "disallowed" in c.lower() or "bypass" in c.lower() or "trust_level" in c])
        self.assertEqual(lr.build_command("p", "/w")[:2], ["codex", "exec"])  # codex unchanged

    def test_router_command_adds_host_claude_only_for_claude(self):
        self.assertEqual(lr.build_mer_command("t", "/w", host="claude")[-3:-1], ["--host", "claude"])
        self.assertNotIn("--host", lr.build_mer_command("t", "/w"))

    def test_env_pins_the_chosen_host_and_baseline_keeps_the_guard(self):
        for host in ("codex", "claude"):
            self.assertEqual(lr.build_env("router", "/s", {"MER_HOST": "other"}, host)["MER_HOST"], host)
        env = lr.build_env("baseline", "/s", {}, "claude")
        self.assertEqual((env["MER_HOST"], env["MER_CLASSIFIER"]), ("claude", "1"))

    def test_baseline_record_usage_cost_thread_and_workdir(self):
        (self.fixture / ".claude").mkdir()
        (self.fixture / ".claude" / "settings.json").write_text("{}")
        rec = self.run_claude("baseline")
        call = self.calls[0]
        self.assertEqual((call["cmd"][0], call["cmd"][-1], call["env"]["MER_HOST"], call["env"]["MER_CLASSIFIER"]),
                         ("claude", "Fix the bug in calc.py", "claude", "1"))
        self.assertEqual(call["cmd"][-2], "--")
        self.assertTrue(call["had_hooks"])  # .codex belongs to codex: only .claude is removed for a claude baseline
        self.assertFalse(call["had_claude"])
        self.assertEqual((rec["host"], rec["thread_ids"], rec["cost_usd"]), ("claude", ["CS1"], 0.0123))
        self.assertEqual(rec["usage"]["total"], 330 + 5)  # input + cache creation + cache read, plus output
        self.assertEqual(rec["usage"]["orchestrator"], {"input": 330, "cached_input": 300, "output": 5, "reasoning_output": 0})
        self.assertIsNone(rec["usage"]["classifier"])
        self.assertEqual(rec["usage"]["incomplete_reasons"], [])
        self.assertFalse(rec["contaminated"])

    def test_baseline_contaminated_only_by_route_events(self):
        self.assertTrue(self.run_claude("baseline", events=[ROUTE])["contaminated"])

    def test_baseline_without_reported_cost_has_none(self):
        body = json.loads(CLAUDE_RESULT)
        del body["total_cost_usd"]
        self.claude = json.dumps(body)
        self.assertIsNone(self.run_claude("baseline")["cost_usd"])

    def test_malformed_and_error_results_are_normal_error_records(self):
        for bad in ("not json", claude_result().replace('"is_error": false', '"is_error": true')):
            self.claude = bad
            rec = self.run_claude("baseline")
            self.assertEqual((rec["host"], "error" in rec, rec["gate_overall"]), ("claude", True, "incomplete"))
            self.assertIn("ClaudeResultError", rec["error"])

    def call(self, role, tid, cost, i=100, o=10):
        c = {"role": role, "thread_id": tid, "usage": {"input": i, "cached_input": 0, "output": o, "reasoning_output": 0}}
        if cost is not None:
            c["host_reported"] = {"total_cost_usd": cost}
        return c

    def test_router_usage_from_mer_calls_only_and_cost_is_last_per_thread(self):
        self.mer = {**MER, "threads": ["S1", "R1"], "calls": [
            self.call("implement", "S1", 0.10), self.call("escalate", "S1", 0.25),  # cumulative: only 0.25 counts
            self.call("review", "R1", 0.05)]}
        rec = self.run_claude("router")
        self.assertEqual(rec["cost_usd"], 0.30)
        self.assertEqual(rec["host"], "claude")
        self.assertIn("--host", self.calls[0]["cmd"])
        self.assertEqual(self.calls[0]["env"]["MER_HOST"], "claude")
        # no rollouts: all three calls come from mer's own report, the codex fixture rollouts are not read
        self.assertEqual(rec["usage"]["total"], 3 * 110 + 29777)  # + the classifier tokens of ROUTE
        self.assertEqual(rec["thread_ids"], ["S1", "R1"])

    def test_router_cost_is_none_when_anything_lacks_it(self):
        ok = lambda role, tid: self.call(role, tid, 0.1)
        cases = {"review without cost": [ok("implement", "S1"), self.call("review", "R1", None)],
                 "timed-out resume on the implement thread": [ok("implement", "S1"), self.call("escalate", "S1", None)],
                 "review call without a thread id": [ok("implement", "S1"), self.call("review", None, 0.05)],
                 "no calls": []}
        for name, calls in cases.items():
            self.mer = {**MER, "threads": ["S1", "R1"], "calls": calls}
            with self.subTest(name):
                self.assertIsNone(self.run_claude("router")["cost_usd"])
        self.mer = {**MER, "status": "error", "threads": ["S1"], "calls": [ok("implement", "S1")]}
        self.assertIsNone(self.run_claude("router")["cost_usd"])  # an errored run is incomplete
        self.mer = {**MER, "threads": ["S1"], "calls": [self.call("implement", "S1", 0.1), self.call("escalate", "S1", 0.3)]}
        self.assertEqual(self.run_claude("router")["cost_usd"], 0.3)

    def with_models(self, call, models):
        call["host_reported"] = {**call.get("host_reported", {}), "modelUsage": models}
        return call

    def test_model_usage_last_per_thread_converted_and_summed(self):
        opus = lambda i, r, c, o: {"claude-opus-5-5": {"inputTokens": i, "cacheReadInputTokens": r,
                                                       "cacheCreationInputTokens": c, "outputTokens": o, "costUSD": 1}}
        haiku = {"claude-haiku-4-5": {"inputTokens": 5, "outputTokens": 1}}
        self.mer = {**MER, "threads": ["S1", "R1"], "calls": [
            self.with_models(self.call("implement", "S1", 0.1), opus(1, 2, 3, 4)),
            self.with_models(self.call("escalate", "S1", 0.2), {**opus(10, 20, 30, 40), **haiku}),  # cumulative: this wins
            self.with_models(self.call("review", "R1", 0.05), opus(100, 0, 0, 7))]}
        mu = self.run_claude("router")["model_usage"]
        self.assertEqual(mu["claude-opus-5-5"], {"input": 60 + 100, "cached_input": 20, "cache_write": 30, "output": 47})
        self.assertEqual(mu["claude-haiku-4-5"], {"input": 5, "cached_input": 0, "cache_write": 0, "output": 1})

    def test_model_usage_none_when_any_call_lacks_it_and_for_baseline_shapes(self):
        self.mer = {**MER, "threads": ["S1"], "calls": [self.with_models(self.call("implement", "S1", 0.1), {"m": {"inputTokens": 1}}),
                                                         self.call("escalate", "S1", 0.2)]}
        self.assertIsNone(self.run_claude("router")["model_usage"])
        body = json.loads(CLAUDE_RESULT)
        self.assertIsNone(self.run_claude("baseline")["model_usage"])  # absent
        body["modelUsage"] = {"claude-sonnet-5-5": {"inputTokens": 10, "cacheReadInputTokens": 300,
                                                    "cacheCreationInputTokens": 20, "outputTokens": 5}}
        self.claude = json.dumps(body)
        self.assertEqual(self.run_claude("baseline")["model_usage"],
                         {"claude-sonnet-5-5": {"input": 330, "cached_input": 300, "cache_write": 20, "output": 5}})
        body["modelUsage"] = {"m": "odd"}
        self.claude = json.dumps(body)
        self.assertIsNone(self.run_claude("baseline")["model_usage"])

    def test_codex_records_have_host_codex_and_no_cost(self):
        rec = self.run_case("router")
        self.assertEqual(rec["host"], "codex")
        self.assertNotIn("cost_usd", rec)



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
                         sessions_dir=self.router_sessions(), gate_fn=lambda cwd: "passed")
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

    def test_repeat_runs_each_case_and_mode_n_times_with_run_numbers_and_diff_names(self):
        rc, _ = self.cli(*self.base_args(), "--live", "--repeat", "2")
        recs = [json.loads(l) for l in self.out.read_text().splitlines()]
        self.assertEqual([(r["case_id"], r["mode"], r["run"]) for r in recs],
                         [("a", "baseline", 1), ("a", "router", 1), ("a", "baseline", 2), ("a", "router", 2)])
        self.assertEqual(sorted(p.name for p in self.out.with_name(self.out.stem + "-diffs").glob("*.diff")),
                         ["a.baseline.r1.diff", "a.baseline.r2.diff", "a.router.r1.diff", "a.router.r2.diff"])
        self.assertEqual(self.cli(*self.base_args(), "--live", "--repeat", "0")[0], 1)
        self.assertEqual(len(self.calls), 4)

    def test_modes_runs_only_the_chosen_mode_and_rejects_unknown(self):
        rc, out = self.cli(*self.base_args(), "--modes", "baseline")
        self.assertIn("1 cases x 1 modes x 1 repeat(s) = 1 runs", out)
        rc, _ = self.cli(*self.base_args(), "--live", "--modes", "baseline")
        recs = [json.loads(l) for l in self.out.read_text().splitlines()]
        self.assertEqual((rc, [(r["case_id"], r["mode"]) for r in recs], len(self.calls)), (0, [("a", "baseline")], 1))
        for bad in ("", "basline", "baseline,oops"):
            self.assertEqual(self.cli(*self.base_args(), "--live", "--modes", bad)[0], 1)
        self.assertEqual(len(self.calls), 1)

    def test_router_backend_flags_dry_run_banner_and_config(self):
        _, out = self.cli(*self.base_args(), "--router-backend", "jev", "--repeat", "2")
        self.assertIn("2 repeat(s) = 4 runs", out)
        self.assertIn("backend jev, fallback subscription", out)
        self.assertEqual(self.calls, [])
        self.cli(*self.base_args(), "--live", "--router-backend", "jev")
        for needle in ("TypeSafe", "external API", "billed separately", "subscription"):
            self.assertIn(needle, self.err)
        self.assertEqual(json.loads(self.calls[1]["config"])["difficulty"], {"backend": "jev", "fallback": "subscription"})
        self.assertIsNone(self.calls[0]["config"])  # baseline
        self.cli(*self.base_args(), "--live", "--router-backend", "jev", "--router-fallback", "none")
        self.assertEqual(json.loads(self.calls[3]["config"])["difficulty"]["fallback"], "none")

    def test_no_router_backend_means_no_typesafe_notice(self):
        self.cli(*self.base_args(), "--live")
        self.assertNotIn("TypeSafe", self.err)

    def test_unknown_router_backend_is_rejected(self):
        with self.assertRaises(SystemExit):
            self.cli(*self.base_args(), "--router-backend", "nope")

    def test_subagent_policy_flag_printed_in_dry_run_written_to_config_and_recorded(self):
        _, out = self.cli(*self.base_args(), "--subagent-policy", "codex")
        self.assertIn("router subagent policy: codex", out)
        self.assertEqual(self.calls, [])
        self.cli(*self.base_args(), "--live", "--subagent-policy", "codex")
        router_call = [c for c in self.calls if c["cmd"][0] != "codex"][0]
        self.assertEqual(json.loads(router_call["config"])["session"], {"subagent_policy": "codex"})
        recs = [json.loads(l) for l in self.out.read_text().splitlines()]
        self.assertEqual([r["subagent_policy"] for r in recs if r["mode"] == "router"], ["codex"])
        with self.assertRaises(SystemExit):
            self.cli(*self.base_args(), "--subagent-policy", "all")

    def test_host_claude_dry_run_live_run_banner_and_records(self):
        self.claude = CLAUDE_RESULT
        _, out = self.cli(*self.base_args(), "--host", "claude")
        lines = {l.split()[0]: l for l in out.splitlines() if l.startswith(("baseline ", "router "))}
        self.assertIn("'claude', '-p'", lines["baseline"])
        self.assertIn("'--', 'Fix the bug in calc.py'", lines["baseline"])
        self.assertIn("'--host', 'claude'", lines["router"])
        self.assertEqual(self.calls, [])
        self.cli(*self.base_args(), "--host", "claude", "--live")
        for needle in ("claude -p", "Claude subscription usage", "No Codex trust entry", "MER_CLASSIFIER=1"):
            self.assertIn(needle, self.err)
        self.assertNotIn("trust_level", self.err)
        recs = [json.loads(l) for l in self.out.read_text().splitlines()]
        self.assertEqual({r["mode"]: r["host"] for r in recs}, {"baseline": "claude", "router": "claude"})
        self.assertEqual(recs[0]["cost_usd"], 0.0123)

    def test_default_host_is_codex_with_the_unchanged_banner(self):
        self.cli(*self.base_args(), "--live")
        self.assertIn("trust_level", self.err)
        self.assertEqual({json.loads(l)["host"] for l in self.out.read_text().splitlines()}, {"codex"})

    def test_live_banner_states_preconditions_and_trust_side_effect(self):
        self.cli(*self.base_args(), "--live")
        for needle in ("subscription usage", "plugin", "trust_level", "config.toml", "installed globally", "mer"):
            self.assertIn(needle, self.err)
        self.assertNotIn("bypass", self.err.replace("does not use", ""))

    def test_live_run_saves_diffs_in_a_directory_per_output_file(self):
        self.cli(*self.base_args(), "--live")
        diffs = self.out.with_name(self.out.stem + "-diffs")  # a later pilot with another --out never overwrites them
        self.assertEqual(sorted(p.name for p in diffs.glob("*.diff")), ["a.baseline.r1.diff", "a.router.r1.diff"])
        recs = [json.loads(l) for l in self.out.read_text().splitlines()]
        self.assertEqual([Path(r["diff_path"]).name for r in recs], ["a.baseline.r1.diff", "a.router.r1.diff"])

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

    def test_baseline_model_effort_in_plan_and_records_router_runs_mer(self):
        args = self.base_args() + ["--model", "dflt", "--baseline-model", "gpt-6-luna", "--baseline-effort", "high"]
        _, out = self.cli(*args)
        lines = {l.split()[0]: l for l in out.splitlines() if l.startswith(("baseline ", "router "))}
        self.assertIn("'gpt-6-luna'", lines["baseline"])
        self.assertIn("model_reasoning_effort=high", lines["baseline"])
        self.assertIn("model_effort_router.cli", lines["router"])
        self.assertNotIn("dflt", lines["router"])
        self.cli(*args, "--live")
        recs = [json.loads(l) for l in self.out.read_text().splitlines()]
        got = {r["mode"]: (r["model"], r["effort"]) for r in recs}
        self.assertEqual(got, {"baseline": ("gpt-6-luna", "high"), "router": ("gpt-6-luna", "medium")})
        cmds = {c["env"].get("MER_CLASSIFIER", "router"): c["cmd"] for c in self.calls}
        self.assertEqual(cmds["1"][cmds["1"].index("-m") + 1], "gpt-6-luna")
        self.assertIn("model_effort_router.cli", cmds["router"])

    def test_case_selects_ids_and_rejects_unknown_or_non_route(self):
        rc, out = self.cli(*self.base_args(), "--case", "a")
        self.assertEqual(rc, 0)
        self.assertIn("1 cases", out)
        for bad in ("zz", "b"):  # b is plan_only
            self.assertEqual(self.cli(*self.base_args(), "--live", "--case", bad)[0], 1)
            self.assertIn(bad, self.err)
        self.assertEqual(self.calls, [])

    def test_limit_and_missing_fixture(self):
        self.assertEqual(self.cli(*self.base_args(), "--live", "--limit", "0")[0], 1)
        bad = self.base_args()
        bad[3] = str(self.root / "nope")
        self.assertEqual(self.cli(*bad, "--live")[0], 1)


if __name__ == "__main__":
    unittest.main()

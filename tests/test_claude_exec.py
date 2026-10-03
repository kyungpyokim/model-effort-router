import io
import json
import os
import tempfile
import unittest
import unittest.mock
from unittest import mock

from model_effort_router import cli
from model_effort_router.adapters.claude import HAIKU, ClaudeConfig
from model_effort_router.difficulty.decision import DifficultyDecision, DifficultyInput
from model_effort_router.difficulty.subscription import BackendOutputError, SubscriptionBackend
from model_effort_router.flow import SUBAGENT_HINT, run_flow
from model_effort_router.host import claude_exec as cx
from model_effort_router.host import hosts
from model_effort_router.policy.session import session_plan
from model_effort_router.profiles.profiles import Profile
from tests.test_mer_cli import CliCase
from tests.test_mer_flow import GATE_BAD, GATE_OK, REPO, REQ

_TMP = tempfile.TemporaryDirectory()


def setUpModule():  # hermetic: never read the developer's real ~/.claude/settings.json
    os.environ["CLAUDE_CONFIG_DIR"] = _TMP.name


def tearDownModule():
    os.environ.pop("CLAUDE_CONFIG_DIR", None)
    _TMP.cleanup()


P = Profile("frontier", "high")
FULL = ClaudeConfig(context="full")  # the unrestricted argv (session.claude_context = "full")
LEAN_FLAGS = ["--strict-mcp-config"]  # no plugins enabled (hermetic settings dir): nothing to switch off


def result(sid="S1", text="done", i=10, created=20, read=300, o=5, **over):
    body = {"type": "result", "subtype": "success", "is_error": False, "session_id": sid, "result": text,
            "usage": {"input_tokens": i, "cache_creation_input_tokens": created, "cache_read_input_tokens": read,
                      "output_tokens": o}, "total_cost_usd": 0.01}
    body.update(over)
    return json.dumps(body)


class ArgvTest(unittest.TestCase):
    def test_implement_argv(self):
        argv = cx.session_argv(P, "do it", "workspace-write", FULL)
        self.assertEqual(argv, ["claude", "-p", "--output-format", "json", "--model", "claude-opus-5-5", "--effort", "high",
                                "--permission-mode", "auto", "--", "do it"])

    def test_subagent_mapping(self):
        self.assertEqual(cx.session_argv(P, "p", "workspace-write", FULL, subagents=0)[-4:-1], ["--disallowedTools", "Agent", "--"])
        for n in (None, 1, 3):  # no hard cap exists: allowed stays allowed, the prompt hint carries the limit
            self.assertNotIn("--disallowedTools", cx.session_argv(P, "p", "workspace-write", subagents=n))
            self.assertNotIn("--disallowedTools", cx.resume_argv(P, "S", "p", subagents=n))

    def test_resume_argv_adds_resume_before_the_prompt(self):
        argv = cx.resume_argv(Profile("balanced", "high"), "S1", "fix it", FULL, subagents=0)
        self.assertEqual(argv[:8], ["claude", "-p", "--output-format", "json", "--model", "claude-sonnet-5-5", "--effort", "high"])
        self.assertEqual(argv[8:], ["--permission-mode", "auto", "--disallowedTools", "Agent", "--resume", "S1", "--", "fix it"])

    def test_read_only_review_argv_always_denies_agent(self):
        for n in (None, 0, 1):
            argv = cx.session_argv(P, "review", "read-only", FULL, subagents=n)
            self.assertEqual(argv[8:], ["--permission-mode", "dontAsk", "--tools", "Read,Grep,Glob", "--allowedTools",
                                        "Read,Grep,Glob", "--disallowedTools", "Agent", "--strict-mcp-config",
                                        "--setting-sources", "user", "--", "review"])

    def test_read_only_sessions_restrict_the_tool_set_itself_and_isolate_settings(self):
        argv = cx.session_argv(P, "p", "read-only", FULL)
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Grep,Glob")  # not only pre-approved
        self.assertIn("--strict-mcp-config", argv)
        self.assertNotIn("--mcp-config", argv)
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "user")  # no project/local permissions or hooks
        for tool in ("Edit", "Write", "Bash"):
            self.assertNotIn(tool, " ".join(argv[:-2]))
        self.assertNotIn("--tools", cx.session_argv(P, "p", "workspace-write", FULL))  # implement keeps the full tool set

    def test_lean_is_the_default_and_adds_the_context_flags_to_every_session(self):
        self.assertEqual(ClaudeConfig().context, "lean")
        impl = cx.session_argv(P, "do it", "workspace-write", subagents=0)
        self.assertEqual(impl[8:], ["--permission-mode", "auto", "--disallowedTools", "Agent", *LEAN_FLAGS, "--", "do it"])
        res = cx.resume_argv(P, "S1", "fix", subagents=0)
        self.assertEqual(res[8:], ["--permission-mode", "auto", "--disallowedTools", "Agent", *LEAN_FLAGS, "--resume", "S1", "--", "fix"])
        ro = cx.session_argv(P, "r", "read-only")
        self.assertEqual(ro[8:], ["--permission-mode", "dontAsk", "--tools", "Read,Grep,Glob", "--allowedTools", "Read,Grep,Glob",
                                  "--disallowedTools", "Agent", "--strict-mcp-config", "--setting-sources", "user", "--settings",
                                  '{"disableAllHooks": true}', "--", "r"])

    def test_lean_never_uses_safe_mode_bare_or_setting_sources_for_implement(self):
        for argv in (cx.session_argv(P, "p", "workspace-write"), cx.resume_argv(P, "S", "p"), cx.session_argv(P, "p", "read-only")):
            self.assertFalse([a for a in argv if a in ("--safe-mode", "--bare")])  # they would drop CLAUDE.md / need an API key
            self.assertIn("--strict-mcp-config", argv)
        for argv in (cx.session_argv(P, "p", "workspace-write"), cx.resume_argv(P, "S", "p")):
            self.assertNotIn("--setting-sources", argv)  # all sources load: ~/.claude/rules and user settings survive

    def test_read_only_never_loads_project_or_local_settings_in_either_mode(self):
        for config in (ClaudeConfig(), FULL, ClaudeConfig(context="lean", plugins_off=lambda: {"x": False})):
            argv = cx.session_argv(P, "p", "read-only", config)
            sources = argv[argv.index("--setting-sources") + 1].split(",")
            self.assertEqual(sources, ["user"])
            self.assertFalse({"project", "local"} & set(sources))
        lean = cx.session_argv(P, "p", "read-only")
        self.assertEqual(lean[lean.index("--settings") + 1], '{"disableAllHooks": true}')  # a reviewed change cannot run hooks
        self.assertNotIn("--settings", cx.session_argv(P, "p", "read-only", FULL))  # full: exactly the old argv

    def test_lean_implement_switches_enabled_plugins_off_via_settings(self):
        cfg = ClaudeConfig(plugins_off=lambda: {"superpowers@m": False, "caveman@m": False})
        for argv in (cx.session_argv(P, "p", "workspace-write", cfg), cx.resume_argv(P, "S", "p", cfg)):
            self.assertEqual(json.loads(argv[argv.index("--settings") + 1]), {"enabledPlugins": {"superpowers@m": False, "caveman@m": False}})
            self.assertLess(argv.index("--settings"), argv.index("--"))
            self.assertIn("--strict-mcp-config", argv)
        self.assertNotIn("--settings", cx.session_argv(P, "p", "workspace-write", ClaudeConfig(plugins_off=lambda: {})))  # none enabled
        self.assertNotIn("--settings", cx.session_argv(P, "p", "workspace-write", ClaudeConfig(context="full", plugins_off=lambda: {"x": False})))

    def test_plugins_off_reads_user_project_and_local_settings_and_never_crashes(self):
        files = {"/u/settings.json": json.dumps({"enabledPlugins": {"a@m": True, "b@m": False, "c@m": "yes"}, "hooks": {}}),
                 "/w/.claude/settings.json": json.dumps({"enabledPlugins": {"d@m": True}}),
                 "/w/.claude/settings.local.json": json.dumps({"enabledPlugins": {"a@m": True, "e@m": True}})}

        def read(path):
            return files[path]  # KeyError for anything unlisted

        with unittest.mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/u"}):
            self.assertEqual(cx.plugins_off("/w", lambda p: files.get(p) or (_ for _ in ()).throw(OSError(p))),
                             {"a@m": False, "d@m": False, "e@m": False})  # only value true counts, deduplicated
            self.assertEqual(cx.plugins_off(None, lambda p: files[p]), {"a@m": False})  # no cwd: user settings only
            def boom(p):
                raise OSError("nope")
            for bad in (boom, lambda p: "{not json", lambda p: "[]", lambda p: "null", lambda p: json.dumps({"enabledPlugins": "x"}),
                        lambda p: json.dumps({"enabledPlugins": ["a"]}), lambda p: json.dumps({})):
                self.assertEqual(cx.plugins_off("/w", bad), {})
            def partial(p):
                return files[p] if p == "/w/.claude/settings.json" else (_ for _ in ()).throw(OSError(p))
            self.assertEqual(cx.plugins_off("/w", partial), {"d@m": False})  # one bad/missing file does not hide the others

    def test_plugins_off_default_reader_uses_claude_config_dir_and_real_files(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as w, unittest.mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": d}):
            pathlib = __import__("pathlib")
            pathlib.Path(d, "settings.json").write_text('{"enabledPlugins": {"x@m": true}}')
            pathlib.Path(w, ".claude").mkdir()
            pathlib.Path(w, ".claude", "settings.local.json").write_text('{"enabledPlugins": {"y@m": true}}')
            self.assertEqual(cx.plugins_off(w), {"x@m": False, "y@m": False})
            argv = cx.session_argv(P, "p", "workspace-write", ClaudeConfig(plugins_off=lambda: cx.plugins_off(w)))
            self.assertEqual(json.loads(argv[argv.index("--settings") + 1]), {"enabledPlugins": {"x@m": False, "y@m": False}})

    def test_full_context_has_no_context_flags_for_implement_and_user_settings_for_read_only(self):
        for argv in (cx.session_argv(P, "p", "workspace-write", FULL), cx.resume_argv(P, "S", "p", FULL)):
            self.assertNotIn("--setting-sources", argv)
            self.assertNotIn("--strict-mcp-config", argv)
        self.assertEqual(cx.session_argv(P, "p", "read-only", FULL)[-5:-2], ["--strict-mcp-config", "--setting-sources", "user"])

    def test_context_validated(self):
        with self.assertRaises(ValueError):
            ClaudeConfig(context="all")

    def test_no_safety_bypass_anywhere(self):
        for argv in (cx.session_argv(P, "p", "workspace-write"), cx.session_argv(P, "p", "read-only"), cx.resume_argv(P, "S", "p")):
            self.assertFalse([a for a in argv if "bypass" in a.lower() or "dangerously" in a.lower()])

    def test_model_without_effort_support_gets_no_effort_flag(self):
        cfg = ClaudeConfig(tiers={"economy": HAIKU, "balanced": HAIKU, "frontier": HAIKU})
        argv = cx.session_argv(P, "p", "workspace-write", cfg)
        self.assertEqual(argv[argv.index("--model") + 1], HAIKU)
        self.assertNotIn("--effort", argv)
        self.assertNotIn("--effort", cx.resume_argv(P, "S", "p", cfg))

    def test_prompt_with_dashes_stays_a_prompt(self):
        self.assertEqual(cx.session_argv(P, "--model evil", "workspace-write")[-2:], ["--", "--model evil"])

    def test_env_guard(self):
        self.assertEqual(cx.session_env({"A": "1"}), {"A": "1", "MER_CLASSIFIER": "1"})


class ParseTest(unittest.TestCase):
    def test_good_result_and_usage_mapping(self):
        s = cx.parse_stream(result(i=10, created=20, read=300, o=5))
        self.assertEqual((s.thread_id, s.text), ("S1", "done"))
        self.assertEqual(s.usage, {"input": 330, "cached_input": 300, "output": 5, "reasoning_output": 0})

    def test_cache_fields_optional_core_counts_required(self):
        body = json.loads(result())
        del body["usage"]["cache_creation_input_tokens"], body["usage"]["cache_read_input_tokens"]
        self.assertEqual(cx.parse_stream(json.dumps(body)).usage["input"], 10)
        for key in ("input_tokens", "output_tokens"):
            bad = json.loads(result())
            del bad["usage"][key]
            with self.subTest(key=key), self.assertRaises(cx.ClaudeResultError):
                cx.parse_stream(json.dumps(bad))

    def test_error_result_raises_with_its_reason(self):
        with self.assertRaises(cx.ClaudeResultError) as cm:
            cx.parse_stream(result(is_error=True, subtype="error_max_turns", text=None))
        self.assertIn("error_max_turns", str(cm.exception))
        # live 2026-10-03: an expired login is subtype "success" + is_error, the reason only in `result`
        expired = "Failed to authenticate: OAuth session expired and could not be refreshed"
        with self.assertRaises(cx.ClaudeResultError) as cm:
            cx.parse_stream(result(is_error=True, subtype="success", text=expired))
        self.assertIn("OAuth session expired", str(cm.exception))

    def test_malformed_or_unknown_shapes_raise_value_errors(self):
        good = json.loads(result())
        bad = ["", "not json", "[]", "null", json.dumps({**good, "type": "assistant"}),
               json.dumps({k: v for k, v in good.items() if k != "session_id"}),
               json.dumps({**good, "session_id": ""}), json.dumps({**good, "result": None}),
               json.dumps({**good, "usage": "x"}), json.dumps({k: v for k, v in good.items() if k != "is_error"}),
               json.dumps({**good, "usage": {**good["usage"], "output_tokens": "5"}}),
               json.dumps({**good, "usage": {**good["usage"], "output_tokens": -1}}),
               json.dumps({**good, "usage": {**good["usage"], "input_tokens": True}})]
        for text in bad:
            with self.subTest(text=text[:40]), self.assertRaises(ValueError):
                cx.parse_stream(text)

    def test_usage_tracker_does_not_subtract(self):
        t = cx.UsageTracker()
        u = {"input": 100, "cached_input": 50, "output": 7, "reasoning_output": 0}
        self.assertEqual(t.delta("S", u), u)
        self.assertEqual(t.delta("S", u), u)  # a resume reports its own usage again, not a running total
        self.assertIsNone(t.delta("S", None))
        self.assertIsNot(t.delta("S", u), u)


class ClaudeRunner:
    """Scripted `claude -p` runner for the host-agnostic flow."""

    def __init__(self, verdicts=()):
        self.calls, self.verdicts, self.n = [], list(verdicts), 0

    def __call__(self, argv, *, cwd, env, timeout_s):
        self.calls.append({"argv": argv, "cwd": cwd, "env": env})
        self.n += 1
        if "--tools" in argv:
            v = self.verdicts.pop(0) if self.verdicts else ("approved", 0)
            return result("R1", f"ok\nVERDICT: {v[0]}\nFINDINGS: {v[1]}", i=500, created=0, read=0, o=20)
        return result("S1", "implemented", i=100 * self.n, created=0, read=10, o=10)


def decision(level, flags=()):
    return DifficultyDecision(level, "fake", risk_flags=tuple(flags))


class FlowTest(unittest.TestCase):
    def run_it(self, level, gates=(GATE_OK,), verdicts=(), flags=(), policy="level"):
        sp = session_plan(decision(level, flags), flags, None, policy)
        runner, queue = ClaudeRunner(verdicts), list(gates)
        def gate(cwd):
            return queue.pop(0) if len(queue) > 1 else queue[0]
        events = []
        out = run_flow(REQ, sp, cwd="/w", runner=runner, env={"A": "1"}, gate_fn=gate, diff_fn=lambda c: REPO,
                       emit=events.append, host=hosts.CLAUDE)
        return out, runner, events

    def test_host_flows_through_implement_resume_and_review(self):
        out, runner, events = self.run_it("L4", gates=(GATE_BAD, GATE_OK), verdicts=[("changes_requested", 1)])
        self.assertEqual([c["role"] for c in out["calls"]], ["implement", "escalate", "review", "review_fix"])
        a = [c["argv"] for c in runner.calls]
        self.assertEqual(a[0][:2], ["claude", "-p"])
        self.assertIn("auto", a[0])
        self.assertIn("--resume", a[1])
        self.assertEqual(a[1][a[1].index("--resume") + 1], "S1")
        self.assertIn("--tools", a[2])
        self.assertNotIn("--resume", a[2])  # the review is a fresh session
        self.assertEqual(a[3][a[3].index("--resume") + 1], "S1")
        for argv in a:
            self.assertIn("Agent", argv)  # L4: implement denies Agent, the review always does
        self.assertEqual(runner.calls[0]["env"]["MER_CLASSIFIER"], "1")
        self.assertEqual((out["status"], out["escalations"]), ("review_fixed", 1))

    def test_usage_is_per_call_not_differenced(self):
        out, runner, _ = self.run_it("L2", gates=(GATE_BAD, GATE_OK))
        self.assertEqual([c["usage"]["input"] for c in out["calls"]], [110, 210])  # input + cache read, each call alone
        self.assertEqual(out["usage"]["input"], 320)
        self.assertEqual(out["calls"][0]["applied_effort"], "medium")
        self.assertEqual(out["calls"][0]["model"], "claude-sonnet-5-5")

    def test_l5_keeps_agent_allowed_and_adds_the_hint(self):
        out, runner, _ = self.run_it("L5")
        self.assertNotIn("--disallowedTools", runner.calls[0]["argv"])
        self.assertIn(SUBAGENT_HINT, runner.calls[0]["argv"][-1])
        self.assertEqual(out["calls"][0]["subagents"], 1)

    def test_codex_policy_passes_no_agent_flag_to_implement(self):
        _, runner, _ = self.run_it("L2", policy="codex")
        self.assertNotIn("--disallowedTools", runner.calls[0]["argv"])

    def test_error_result_becomes_an_error_status(self):
        sp = session_plan(decision("L2"), (), None)
        out = run_flow(REQ, sp, cwd="/w", runner=lambda argv, **k: result(is_error=True, subtype="error_during_execution", text=None),
                       env={}, gate_fn=lambda c: GATE_OK, diff_fn=lambda c: REPO, emit=lambda e: None, host=hosts.CLAUDE)
        self.assertEqual((out["status"], out["exit_code"]), ("error", 1))
        self.assertIn("error_during_execution", out["error"])

    def test_resume_following_a_new_session_id(self):
        calls = []

        def runner(argv, **k):
            calls.append(argv)
            return result("S2" if "--resume" in argv else "S1", "ok")

        sp = session_plan(decision("L2"), (), None)
        queue = [GATE_BAD, GATE_BAD, GATE_OK]
        run_flow(REQ, sp, cwd="/w", runner=runner, env={}, gate_fn=lambda c: queue.pop(0), diff_fn=lambda c: REPO,
                 emit=lambda e: None, host=hosts.CLAUDE)
        self.assertEqual([a[a.index("--resume") + 1] for a in calls if "--resume" in a], ["S1", "S2"])


class HostReportedTest(unittest.TestCase):
    def test_cost_and_model_usage_kept_as_a_cross_check_and_optional(self):
        s = cx.parse_stream(result(total_cost_usd=0.0123, modelUsage={"claude-opus-5-5": {"inputTokens": 5}}))
        self.assertEqual(s.extra, {"total_cost_usd": 0.0123, "modelUsage": {"claude-opus-5-5": {"inputTokens": 5}}})
        body = json.loads(result())
        del body["total_cost_usd"]
        self.assertIsNone(cx.parse_stream(json.dumps(body)).extra)  # absent: fine
        self.assertIsNone(cx.parse_stream(result(total_cost_usd="x", modelUsage=[1])).extra)  # malformed: ignored, no failure

    def test_flow_records_host_reported_on_the_call(self):
        sp = session_plan(decision("L2"), (), None)
        out = run_flow(REQ, sp, cwd="/w", runner=lambda argv, **k: result(total_cost_usd=0.5), env={},
                       gate_fn=lambda c: GATE_OK, diff_fn=lambda c: REPO, emit=lambda e: None, host=hosts.CLAUDE)
        self.assertEqual(out["calls"][0]["host_reported"], {"total_cost_usd": 0.5})
        bare = json.dumps({k: v for k, v in json.loads(result()).items() if k != "total_cost_usd"})
        out = run_flow(REQ, sp, cwd="/w", runner=lambda argv, **k: bare, env={}, gate_fn=lambda c: GATE_OK,
                       diff_fn=lambda c: REPO, emit=lambda e: None, host=hosts.CLAUDE)
        self.assertNotIn("host_reported", out["calls"][0])


class ContextConfigTest(CliCase):
    def test_config_default_values_and_validation(self):
        from model_effort_router.policy.config import resolve_config
        self.assertEqual(resolve_config().claude_context, "lean")
        self.assertEqual(resolve_config(repo={"session": {"claude_context": "full"}}).claude_context, "full")
        self.assertEqual(resolve_config(repo={"session": {"subagent_policy": "codex"}}).claude_context, "lean")  # keys independent
        for bad in ("none", None, "LEAN"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                resolve_config(repo={"session": {"claude_context": bad}})

    def dry(self, host="claude"):
        out = io.StringIO()
        cli.main(["run", "--cwd", str(self.cwd), "--dry-run", "--level", "L2", "--host", host, "Fix the bug in calc.py"],
                 env=self.env(), out=out)
        return out.getvalue()

    def test_full_in_repo_config_restores_the_unrestricted_argv_in_dry_run(self):
        self.assertIn("--strict-mcp-config", self.dry())
        self.assertNotIn("--setting-sources", self.dry())  # implement: all sources load
        (self.cwd / ".model-effort-router.json").write_text('{"difficulty": {"backend": "fake"}, "session": {"claude_context": "full"}}')
        out = self.dry()
        self.assertNotIn("--setting-sources", out)
        self.assertNotIn("--strict-mcp-config", out)  # full: no context flags on the implement argv

    def test_config_reaches_the_executed_sessions_and_codex_ignores_it(self):
        runner = ClaudeRunner()
        cli.main(["run", "--cwd", str(self.cwd), "--host", "claude", "Fix the bug in calc.py"], env=self.env(), runner=runner,
                 gate_fn=lambda c: GATE_OK, diff_fn=lambda c: REPO, out=io.StringIO())
        self.assertIn("--strict-mcp-config", runner.calls[0]["argv"])
        (self.cwd / ".model-effort-router.json").write_text('{"difficulty": {"backend": "fake"}, "session": {"claude_context": "full"}}')
        runner = ClaudeRunner()
        cli.main(["run", "--cwd", str(self.cwd), "--host", "claude", "Fix the bug in calc.py"], env=self.env(), runner=runner,
                 gate_fn=lambda c: GATE_OK, diff_fn=lambda c: REPO, out=io.StringIO())
        self.assertNotIn("--setting-sources", runner.calls[0]["argv"])
        codex_out = self.dry("codex")
        self.assertNotIn("--setting-sources", codex_out)
        self.assertIn("first command: codex exec", codex_out)


class HostSelectionTest(unittest.TestCase):
    def test_default_env_and_flag(self):
        self.assertIs(hosts.get(), hosts.CODEX)
        self.assertIs(hosts.get(env={}), hosts.CODEX)
        self.assertIs(hosts.get(env={"MER_HOST": "claude"}), hosts.CLAUDE)
        self.assertIs(hosts.get("codex", {"MER_HOST": "claude"}), hosts.CODEX)  # the flag beats the env
        self.assertIs(hosts.get("claude", {}), hosts.CLAUDE)
        with self.assertRaises(ValueError):
            hosts.get("gemini")
        with self.assertRaises(ValueError):
            hosts.get(env={"MER_HOST": "nope"})


class CliHostTest(CliCase):
    def run_cli(self, *argv, env_extra=None, **kw):
        out = io.StringIO()
        env = {**self.env(), **(env_extra or {})}
        rc = cli.main(["run", "--cwd", str(self.cwd), *argv], env=env, out=out, **kw)
        return rc, out.getvalue()

    def test_dry_run_default_host_is_codex(self):
        _, out = self.run_cli("--dry-run", "--level", "L2", "Fix the bug in calc.py")
        self.assertIn("host: codex", out)
        self.assertIn("first command: codex exec", out)

    def test_dry_run_shows_the_claude_argv_by_flag_and_by_env(self):
        for argv, extra in ((["--host", "claude"], None), ([], {"MER_HOST": "claude"})):
            with self.subTest(argv=argv):
                _, out = self.run_cli("--dry-run", "--level", "L2", *argv, "Fix the bug in calc.py", env_extra=extra)
                self.assertIn("host: claude", out)
                self.assertIn("session: economy:medium -> claude-sonnet-5-5/medium", out)
                self.assertIn("first command: claude -p --output-format json --model claude-sonnet-5-5 --effort medium "
                              "--permission-mode auto --disallowedTools Agent --strict-mcp-config -- ", out)

    def test_flag_beats_env_and_bad_host_is_exit_2(self):
        _, out = self.run_cli("--dry-run", "--level", "L2", "--host", "codex", "x.py", env_extra={"MER_HOST": "claude"})
        self.assertIn("host: codex", out)
        rc, _ = self.run_cli("--dry-run", "--level", "L2", "x.py", env_extra={"MER_HOST": "nope"})
        self.assertEqual(rc, 2)

    def test_l4_dry_run_claude_review_profile_lines(self):
        _, out = self.run_cli("--dry-run", "--level", "L4", "--host", "claude", "Fix the bug in calc.py")
        self.assertIn("session: frontier:high -> claude-opus-5-5/high", out)
        self.assertIn("review: frontier:high -> claude-opus-5-5/high", out)

    def test_run_executes_claude_sessions_and_logs_session_ids(self):
        runner = ClaudeRunner()
        out = io.StringIO()
        rc = cli.main(["run", "--cwd", str(self.cwd), "--host", "claude", "--json", "Fix the bug in calc.py"], env=self.env(),
                      runner=runner, gate_fn=lambda c: GATE_OK, diff_fn=lambda c: REPO, out=out)
        res = json.loads(out.getvalue())
        self.assertEqual((rc, res["status"], res["threads"], res["profile"]["model"]), (0, "ok", ["S1"], "claude-sonnet-5-5"))
        self.assertEqual(runner.calls[0]["argv"][0], "claude")

    def test_chat_dry_run_prints_interactive_claude_and_cwd(self):
        out = io.StringIO()
        cli.main(["chat", "--cwd", str(self.cwd), "--host", "claude", "--dry-run", "--level", "L4", "Fix the bug in calc.py"],
                 env=self.env(), out=out)
        text = out.getvalue()
        self.assertIn("command: claude --model claude-opus-5-5 --effort high -- 'Fix the bug in calc.py", text)
        self.assertNotIn(" -p ", text)
        self.assertIn(f"cwd: {self.cwd}", text)

    def test_chat_execs_claude_after_chdir_with_guard_env(self):
        calls = []
        with mock.patch("os.chdir") as chdir:
            cli.main(["chat", "--cwd", str(self.cwd), "--host", "claude", "--level", "L2", "--dry-run", "x.py"],
                     env=self.env(), out=io.StringIO())
            chdir.assert_not_called()  # dry-run changes nothing
        def cli_main():
            return cli.main(["chat", "--cwd", str(self.cwd), "--host", "claude", "Fix the bug in calc.py"],
                                           env=self.env(), out=io.StringIO(), exec_fn=lambda f, a, e: calls.append((f, a, e)))
        with mock.patch("os.chdir") as chdir:
            cli_main()
        chdir.assert_called_once_with(str(self.cwd))
        prog, argv, env = calls[0]
        self.assertEqual((prog, argv[:3]), ("claude", ["claude", "--model", "claude-sonnet-5-5"]))
        self.assertEqual(env["MER_CLASSIFIER"], "1")

    def test_chat_plan_only_starts_in_plan_permission_mode(self):
        out = io.StringIO()
        cli.main(["chat", "--cwd", str(self.cwd), "--host", "claude", "--dry-run", "--level", "L3",
                  "write a plan for the parser module"], env=self.env(), out=out)
        self.assertIn("--permission-mode plan", out.getvalue())

    def test_codex_chat_unchanged(self):
        out = io.StringIO()
        cli.main(["chat", "--cwd", str(self.cwd), "--dry-run", "--level", "L2", "Fix the bug in calc.py"], env=self.env(), out=out)
        self.assertIn("command: codex --cd ", out.getvalue())


class ClassifierTest(unittest.TestCase):
    ANSWER = json.dumps({"level": "L3", "confidence": 0.9, "reason_codes": ["multi_file"], "risk_flags": ["auth"]})

    def classify(self, host=None, env=None):
        seen = {}

        def runner(cmd, *, stdin, env, timeout_s, cwd):
            seen.update(cmd=cmd, env=env, cwd=cwd)
            return result("C1", self.ANSWER, i=400, created=0, read=100, o=30)

        backend = SubscriptionBackend(runner=runner, host=host)
        with mock.patch.dict(os.environ, env or {}, clear=False):
            d = backend.classify(DifficultyInput("Fix the login bug"), 10)
        return backend, d, seen

    def test_claude_classifier_argv_has_no_tools_no_persistence_and_the_guard(self):
        _, d, seen = self.classify(host="claude")
        cmd = seen["cmd"]
        self.assertEqual(cmd[:8], ["claude", "-p", "--output-format", "json", "--model", "claude-haiku-4-5",
                                   "--permission-mode", "dontAsk"])
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")
        self.assertIn("--no-session-persistence", cmd)
        self.assertEqual(cmd[-2], "--")
        self.assertNotIn("--effort", cmd)
        for flag in ("--safe-mode", "--strict-mcp-config"):  # no CLAUDE.md/plugins/hooks/MCP: fast and unbiased
            self.assertIn(flag, cmd)
        self.assertNotIn("--mcp-config", cmd)
        self.assertEqual(seen["env"]["MER_CLASSIFIER"], "1")
        self.assertEqual((d.level, d.risk_flags, d.confidence), ("L3", ("auth",), 0.9))

    def test_usage_is_reported_with_the_existing_codex_style_keys(self):
        b, _, _ = self.classify(host="claude")
        self.assertEqual(b.last_usage, {"input_tokens": 500, "cached_input_tokens": 100, "output_tokens": 30,
                                        "reasoning_output_tokens": 0})

    def test_the_backend_never_reads_the_env_for_its_host(self):
        stream = json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": self.ANSWER}})
        for host, first in ((None, "codex"), ("codex", "codex"), ("claude", "claude")):
            seen = {}

            def runner(cmd, **k):
                seen["cmd"] = cmd
                return result("C", self.ANSWER) if cmd[0] == "claude" else stream

            with self.subTest(host=host), mock.patch.dict(os.environ, {"MER_HOST": "claude"}):
                SubscriptionBackend(runner=runner, host=host).classify(DifficultyInput("x"), 5)
            self.assertEqual(seen["cmd"][0], first)

    def test_error_or_malformed_claude_result_is_a_backend_output_error(self):
        for out in (result(is_error=True, subtype="error_during_execution"), "garbage", result(text="not json at all")):
            b = SubscriptionBackend(runner=lambda *a, **k: out, host="claude")
            with self.subTest(out=out[:30]), self.assertRaises(BackendOutputError):
                b.classify(DifficultyInput("x"), 5)


if __name__ == "__main__":
    unittest.main()

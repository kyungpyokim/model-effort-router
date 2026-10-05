import json
import os
import tempfile
import unittest
from unittest import mock

from model_effort_router.adapters.claude import HAIKU, ClaudeConfig
from model_effort_router.adapters.common import ResolvedProfile
from model_effort_router.difficulty.decision import DifficultyInput
from model_effort_router.difficulty.subscription import BackendOutputError, SubscriptionBackend
from model_effort_router.host import claude_exec as cx
from model_effort_router.profiles.profiles import Profile

_TMP = tempfile.TemporaryDirectory()

def setUpModule():
    os.environ["CLAUDE_CONFIG_DIR"] = _TMP.name

def tearDownModule():
    os.environ.pop("CLAUDE_CONFIG_DIR", None)
    _TMP.cleanup()

P = Profile("frontier", "high")
FULL = ClaudeConfig(context="full")
LEAN_FLAGS = ["--strict-mcp-config"]

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



class ResolvedModelArgvTest(unittest.TestCase):
    def test_resolved_primary_and_effort_reach_claude_argv(self):
        selected = ResolvedProfile("reasoning", "claude-opus-5-5", "xhigh", "xhigh")
        argv = cx.session_argv(selected, "review", "read-only")
        self.assertEqual(argv[argv.index("--model") + 1], "claude-opus-5-5")
        self.assertEqual(argv[argv.index("--effort") + 1], "xhigh")

    def test_read_only_tools_remain_restricted_for_resolved_profile(self):
        argv = cx.session_argv(P, "review", "read-only")
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Grep,Glob")
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "user")
        self.assertIn("--disallowedTools", argv)
        self.assertNotIn("Bash", " ".join(argv))


class ClassifierTest(unittest.TestCase):
    ANSWER = json.dumps({"role": "review", "effort": "high", "confidence": 0.9, "reason_code": "diff_review"})

    def classify(self, host=None, env=None):
        seen = {}
        def runner(cmd, *, stdin, env, timeout_s, cwd):
            seen.update(cmd=cmd, env=env, cwd=cwd)
            return result(text=self.ANSWER, i=400, created=0, read=100, o=30)
        backend = SubscriptionBackend(runner=runner, host=host)
        with mock.patch.dict(os.environ, env or {}, clear=False):
            decision = backend.classify(DifficultyInput("Review the auth diff"), 10)
        return backend, decision, seen

    def test_claude_classifier_is_tool_free_and_guarded(self):
        _, decision, seen = self.classify(host="claude")
        cmd = seen["cmd"]
        self.assertEqual(cmd[:6], ["claude", "-p", "--output-format", "json", "--model", "claude-haiku-4-5"])
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")
        self.assertIn("--no-session-persistence", cmd)
        self.assertEqual(cmd[-2], "--")
        self.assertNotIn("--effort", cmd)
        self.assertTrue({"--safe-mode", "--strict-mcp-config"}.issubset(cmd))
        self.assertEqual(seen["env"]["MER_CLASSIFIER"], "1")
        self.assertEqual((decision.role, decision.effort, decision.confidence), ("review", "high", 0.9))

    def test_claude_usage_is_normalized_to_shared_keys(self):
        backend, _, _ = self.classify(host="claude")
        self.assertEqual(backend.last_usage, {"input_tokens": 500, "cached_input_tokens": 100, "output_tokens": 30,
                                             "reasoning_output_tokens": 0})

    def test_host_is_explicit_and_not_inferred_inside_backend(self):
        stream = json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": self.ANSWER}})
        for host, command in ((None, "codex"), ("codex", "codex"), ("claude", "claude")):
            seen = {}
            def runner(cmd, **kwargs):
                seen["cmd"] = cmd
                return result(text=self.ANSWER) if cmd[0] == "claude" else stream
            with self.subTest(host=host), mock.patch.dict(os.environ, {"MER_HOST": "claude"}):
                SubscriptionBackend(runner=runner, host=host).classify(DifficultyInput("x"), 5)
            self.assertEqual(seen["cmd"][0], command)

    def test_malformed_claude_result_fails_classification(self):
        for output in (result(is_error=True, subtype="error_during_execution"), "garbage", result(text="no JSON")):
            backend = SubscriptionBackend(runner=lambda *a, **k: output, host="claude")
            with self.subTest(output=output[:20]), self.assertRaises(BackendOutputError):
                backend.classify(DifficultyInput("x"), 5)

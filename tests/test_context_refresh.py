import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from model_effort_router.context import refresh, summary
from model_effort_router.context.summary import Stored, anchor_at
from model_effort_router.context.transcripts import read_turns
from model_effort_router.difficulty.subscription import GUARD_ENV
from model_effort_router.logging import route_log

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "transcripts"
CLAUDE = str(FIXTURES / "claude-session.jsonl")
CODEX = str(FIXTURES / "codex-rollout.jsonl")
TURNS = read_turns(CLAUDE, "claude")


def claude_result(text):
    return json.dumps({"type": "result", "is_error": False, "session_id": "x", "result": text,
                       "usage": {"input_tokens": 11, "cache_read_input_tokens": 5, "output_tokens": 7}})


class FakeRunner:
    def __init__(self, stdout="", error=None):
        self.stdout, self.error, self.calls = stdout, error, []

    def __call__(self, cmd, *, stdin, env, timeout_s, cwd, **kw):
        self.calls.append({"cmd": cmd, "env": env, "timeout_s": timeout_s, "cwd": cwd, "cwd_files": os.listdir(cwd), **kw})
        if self.error:
            raise self.error
        return self.stdout


class RefreshTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.sdir = os.path.join(self._tmp.name, "state")
        self.env = {"PATH": os.environ.get("PATH", "")}

    def run_refresh(self, host, path, runner, sid="s1", min_chars=1):
        self.assertEqual(refresh.main([host, sid, path, self.sdir], runner=runner, env=self.env, min_chars=min_chars), 0)

    def log_events(self, sid="s1"):
        p = route_log.log_path(self.sdir, sid)
        return [json.loads(line) for line in open(p)] if os.path.exists(p) else []

    def test_claude_folds_uncovered_turns_into_the_stored_summary(self):
        summary.save(self.sdir, "s1", "OLD SUMMARY", anchor_at(TURNS, 2))
        runner = FakeRunner(claude_result("NEW SUMMARY"))
        self.run_refresh("claude", CLAUDE, runner)
        self.assertEqual(summary.load(self.sdir, "s1"), Stored("NEW SUMMARY", anchor_at(TURNS, len(TURNS))))
        (call,) = runner.calls
        cmd = call["cmd"]
        self.assertEqual(cmd[:2], ["claude", "-p"])
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")
        for flag in ("--safe-mode", "--strict-mcp-config", "--no-session-persistence"):
            self.assertIn(flag, cmd)
        self.assertIn("haiku", cmd[cmd.index("--model") + 1])
        prompt = call["input_text"]  # on stdin: transcript text never lands in argv (ps)
        self.assertNotIn("OLD SUMMARY", " ".join(cmd))
        self.assertIn("OLD SUMMARY", prompt)
        self.assertIn("응 만들어줘", prompt)
        self.assertNotIn("Add a retry option", prompt)  # already covered
        self.assertEqual(call["env"][GUARD_ENV], "1")
        self.assertEqual(call["cwd_files"], [])
        self.assertGreaterEqual(call["timeout_s"], 60)
        self.assertFalse(os.path.exists(call["cwd"]))

    def test_prompt_asks_for_bounded_plain_text_and_treats_the_conversation_as_data(self):
        runner = FakeRunner(claude_result("S"))
        self.run_refresh("claude", CLAUDE, runner)
        prompt = runner.calls[0]["input_text"].lower()
        for word in ("goals", "decisions", "constraints", "plans awaiting approval", "open questions",
                     "work in progress", "plain text", str(refresh.SUMMARY_MAX_CHARS), "data"):
            self.assertIn(word, prompt)

    def test_codex_is_not_summarized_until_its_exec_can_run_without_a_shell(self):
        runner = FakeRunner("{}")
        self.run_refresh("codex", CODEX, runner)
        self.assertEqual(runner.calls, [])
        self.assertEqual(refresh.HOSTS, ("claude",))

    def test_summary_is_clipped_to_the_limit(self):
        self.run_refresh("claude", CLAUDE, FakeRunner(claude_result("x" * 9000)))
        self.assertEqual(len(summary.load(self.sdir, "s1").summary), refresh.SUMMARY_MAX_CHARS)

    def test_success_logs_token_counts_and_latency_but_no_text(self):
        self.run_refresh("claude", CLAUDE, FakeRunner(claude_result("NEW SUMMARY TEXT")))
        (event,) = self.log_events()
        self.assertEqual(event["event"], "context_refresh")
        self.assertEqual(event["usage"], {"input_tokens": 16, "cached_input_tokens": 5, "output_tokens": 7})
        self.assertEqual(event["host"], "claude")
        self.assertGreaterEqual(event["latency_ms"], 0)
        self.assertNotIn("NEW SUMMARY TEXT", json.dumps(event))

    def test_failures_keep_the_old_summary_and_log_the_error_type_only(self):
        old = Stored("OLD", anchor_at(TURNS, 1))
        summary.save(self.sdir, "s1", old.summary, old.anchor)
        for runner in (FakeRunner(error=TimeoutError("secret prompt text")), FakeRunner("not json"),
                       FakeRunner(claude_result("   "))):
            self.run_refresh("claude", CLAUDE, runner)
        self.assertEqual(summary.load(self.sdir, "s1"), old)
        events = self.log_events()
        self.assertEqual(len(events), 3)
        self.assertTrue(all(e["event"] == "error" and e["code"] == "context_refresh_failed" for e in events))
        self.assertEqual(events[0]["type"], "TimeoutError")
        self.assertNotIn("secret", json.dumps(events))

    def test_nothing_to_do_never_calls_the_cli(self):
        summary.save(self.sdir, "s1", "S", anchor_at(TURNS, len(TURNS)))
        cases = [("claude", CLAUDE, {}), ("antigravity", CLAUDE, {}), ("claude", "/missing.jsonl", {}),
                 ("claude", CLAUDE, {GUARD_ENV: "1"})]
        for host, path, extra in cases:
            runner = FakeRunner(claude_result("S2"))
            self.env = {**extra}
            with self.subTest(host=host, path=path, extra=extra):
                self.run_refresh(host, path, runner)
                self.assertEqual(runner.calls, [])
        self.assertEqual(summary.load(self.sdir, "s1").summary, "S")

    def test_a_running_refresh_makes_the_next_one_skip(self):
        runner = FakeRunner(claude_result("S2"))
        with summary.locked(self.sdir, "s1"):
            self.run_refresh("claude", CLAUDE, runner)
        self.assertEqual(runner.calls, [])

    def test_small_updates_are_not_summarized_by_default(self):
        runner = FakeRunner(claude_result("S2"))
        self.run_refresh("claude", CLAUDE, runner, min_chars=summary.REFRESH_MIN_CHARS)
        self.assertEqual(runner.calls, [])

    def test_bad_argv_is_ignored(self):
        self.assertEqual(refresh.main(["claude"], runner=FakeRunner(), env=self.env), 0)

    def test_transcript_and_store_are_read_while_holding_the_lock(self):
        """Regression: reading before the lock could save an anchor older than a concurrent refresh's."""
        held = []
        real_read, real_load = refresh.read_turns, summary.load

        def probe(fn):
            def wrapped(*args, **kw):
                with summary.locked(self.sdir, "s1") as got:
                    held.append(not got)
                return fn(*args, **kw)
            return wrapped
        with mock.patch.object(refresh, "read_turns", probe(real_read)), mock.patch.object(summary, "load", probe(real_load)):
            self.run_refresh("claude", CLAUDE, FakeRunner(claude_result("S")))
        self.assertTrue(held and all(held), held)

    def test_old_summary_files_are_pruned_but_not_this_sessions(self):
        summary.save(self.sdir, "other", "x", ())
        stale = time.time() - 20 * 86400
        os.utime(summary.summary_path(self.sdir, "other"), (stale, stale))
        self.run_refresh("claude", CLAUDE, FakeRunner(claude_result("S")))
        self.assertFalse(os.path.exists(summary.summary_path(self.sdir, "other")))
        self.assertTrue(os.path.exists(summary.summary_path(self.sdir, "s1")))


class LongBacklogTest(unittest.TestCase):
    """Regression: turns beyond the prompt budget used to be dropped but still marked covered."""

    def test_only_the_included_turns_are_marked_covered_and_the_rest_follow_next_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.jsonl")
            sdir = os.path.join(tmp, "state")
            texts = [f"turn-{i:02d} " + "y" * 2900 for i in range(14)]  # ~41k chars > MAX_INPUT_CHARS
            with open(path, "w") as f:
                for i, text in enumerate(texts):
                    f.write(json.dumps({"type": "user" if i % 2 == 0 else "assistant", "message": {"content": text}}) + "\n")
            turns = read_turns(path, "claude")
            runner = FakeRunner(claude_result("S1"))
            env = {}
            refresh.main(["claude", "s", path, sdir], runner=runner, env=env, min_chars=1)
            first = runner.calls[0]["input_text"]
            self.assertIn("turn-00", first)
            self.assertNotIn("turn-13", first)
            included = sum(1 for i in range(14) if f"turn-{i:02d}" in first)
            self.assertTrue(0 < included < 14)
            self.assertLessEqual(len(first), refresh.MAX_INPUT_CHARS + len(refresh.PROMPT) + 200)
            self.assertEqual(summary.load(sdir, "s"), Stored("S1", anchor_at(turns, included)))
            runner2 = FakeRunner(claude_result("S2"))
            refresh.main(["claude", "s", path, sdir], runner=runner2, env=env, min_chars=1)
            second = runner2.calls[0]["input_text"]
            self.assertIn(f"turn-{included:02d}", second)
            self.assertNotIn(f"turn-{included - 1:02d}", second)
            self.assertIn("S1", second)


class SpawnTest(unittest.TestCase):
    def test_spawns_a_detached_silent_module_process_that_can_import_the_core(self):
        seen = {}

        def popen(argv, **kw):
            seen.update(argv=argv, **kw)

        refresh.spawn("claude", "s1", "/t.jsonl", "/state", {"PYTHONPATH": "/other", "KEEP": "1"}, popen=popen)
        self.assertEqual(seen["argv"], [sys.executable, "-m", "model_effort_router.context.refresh", "claude", "s1", "/t.jsonl", "/state"])
        self.assertTrue(seen["start_new_session"] and seen["close_fds"])
        for stream in ("stdin", "stdout", "stderr"):
            self.assertEqual(seen[stream], refresh.subprocess.DEVNULL)
        core = str(Path(refresh.__file__).resolve().parents[2])
        self.assertEqual(seen["env"]["PYTHONPATH"].split(os.pathsep), [core, "/other"])
        self.assertEqual(seen["env"]["KEEP"], "1")


if __name__ == "__main__":
    unittest.main()

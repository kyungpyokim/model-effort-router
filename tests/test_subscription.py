import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from model_effort_router.difficulty.decision import DifficultyInput
from model_effort_router.difficulty.subscription import (
    GUARD_ENV,
    MAX_TASK_CHARS,
    BackendOutputError,
    CliAuthError,
    SubscriptionBackend,
    build_prompt,
    default_runner,
)


def event(obj):
    return json.dumps(obj)


def agent_message(text):
    return event({"type": "item.completed", "item": {"type": "agent_message", "text": text}})


GOOD = json.dumps(
    {"role": "implementation", "effort": "high", "confidence": 0.9, "reason_code": "multi_file"}
)


class FakeRunner:
    def __init__(self, stdout="", exc=None):
        self.stdout, self.exc, self.calls = stdout, exc, []

    def __call__(self, cmd, *, stdin, env, timeout_s, cwd, input_text=None):
        self.calls.append(
            {
                "cmd": cmd, "input_text": input_text, "stdin": stdin, "env": env, "timeout_s": timeout_s, "cwd": cwd,
                "cwd_entries": os.listdir(cwd) if cwd and os.path.isdir(cwd) else None,
            }
        )
        if self.exc:
            raise self.exc
        return self.stdout


def classify(stdout="", exc=None, task=None):
    runner = FakeRunner(stdout, exc)
    backend = SubscriptionBackend(runner=runner)
    return backend.classify(task or DifficultyInput(task="add endpoint"), timeout_s=9), runner


class ParsingTest(unittest.TestCase):
    def test_valid_output(self):
        d, _ = classify("\n".join([event({"type": "thread.started"}), agent_message(GOOD)]))
        self.assertEqual((d.role, d.effort), ("implementation", "high"))
        self.assertEqual(d.backend, "subscription")
        self.assertEqual(d.confidence, 0.9)
        self.assertEqual(d.reason_code, "multi_file")

    def test_error_events_are_skipped(self):
        noise = event({"type": "error", "message": 'persistent_instructions ignored {"role": "review"}'})
        d, _ = classify("\n".join([noise, agent_message(GOOD), noise]))
        self.assertEqual(d.role, "implementation")

    def test_non_json_lines_are_skipped(self):
        d, _ = classify("WARNING: something\n" + agent_message(GOOD))
        self.assertEqual(d.role, "implementation")

    def test_fenced_json_accepted(self):
        d, _ = classify(agent_message("```json\n" + GOOD + "\n```"))
        self.assertEqual((d.role, d.effort), ("implementation", "high"))

    def test_minimal_output_requires_role_and_effort(self):
        d, _ = classify(agent_message('{"role": "fix", "effort": "low"}'))
        self.assertEqual((d.role, d.effort, d.confidence), ("fix", "low", None))

    def test_garbage_raises(self):
        for out in ("", "not json at all", agent_message("I think it is hard"), agent_message("{")):
            with self.subTest(out=out), self.assertRaises(BackendOutputError):
                classify(out)

    def test_only_error_events_raises(self):
        with self.assertRaises(BackendOutputError):
            classify(event({"type": "error", "message": GOOD}))

    def test_invalid_fields_raise(self):
        for payload in (
            '{"role": "bogus", "effort": "low"}',
            '{"role": "implementation"}',
            '{"role": "review", "effort": "xhigh", "confidence": 7}',
            '{"role": "review", "effort": "xhigh", "confidence": true}',
            "[1, 2]",
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                classify(agent_message(payload))

    def test_legacy_level_output_is_rejected(self):
        with self.assertRaises(BackendOutputError):
            classify(agent_message('{"level": "L2"}'))

    def test_only_completed_events_count(self):
        started = event({"type": "item.started", "item": {"type": "agent_message", "text": '{"role": "review", "effort": "xhigh"}'}})
        updated = event({"type": "item.updated", "item": {"type": "agent_message", "text": '{"role": "review", "effort": "xhigh"}'}})
        d, _ = classify("\n".join([started, updated, agent_message(GOOD)]))
        self.assertEqual(d.effort, "high")
        with self.assertRaises(BackendOutputError):
            classify("\n".join([started, updated]))

    def test_timeout_propagates(self):
        with self.assertRaises(TimeoutError):
            classify(exc=TimeoutError())


class RunnerContractTest(unittest.TestCase):
    def test_command_stdin_env_timeout(self):
        before = dict(os.environ)
        _, runner = classify(agent_message(GOOD))
        call = runner.calls[0]
        cmd = call["cmd"]
        self.assertEqual(cmd[:3], ["codex", "exec", "--json"])
        for flag in ("--ephemeral", "--skip-git-repo-check", "--ignore-user-config"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index("-s") + 1], "read-only")
        self.assertEqual(cmd[cmd.index("-m") + 1], "gpt-6-luna")
        self.assertIn(["-c", "model_reasoning_effort=low"], [cmd[i:i + 2] for i in range(len(cmd) - 1)])
        self.assertEqual(cmd[-1], "-")  # `codex exec -` reads the prompt from stdin: it stays out of argv
        self.assertIn("add endpoint", call["input_text"])
        self.assertNotIn("add endpoint", " ".join(cmd))
        self.assertIs(call["stdin"], subprocess.DEVNULL)
        self.assertEqual(call["env"][GUARD_ENV], "1")
        self.assertEqual(call["timeout_s"], 9)
        self.assertEqual(dict(os.environ), before)  # guard only on the child env

    def test_runs_in_empty_dir_without_codex_config_and_cleans_up(self):
        _, runner = classify(agent_message(GOOD))
        call = runner.calls[0]
        self.assertNotEqual(os.path.realpath(call["cwd"]), os.path.realpath(os.getcwd()))
        self.assertEqual(call["cwd_entries"], [])  # exists during the call, no .codex/
        self.assertFalse(os.path.exists(call["cwd"]))

    def test_cwd_cleaned_up_when_runner_fails(self):
        runner = FakeRunner(exc=TimeoutError())
        with self.assertRaises(TimeoutError):
            SubscriptionBackend(runner=runner).classify(DifficultyInput("t"), 1)
        self.assertFalse(os.path.exists(runner.calls[0]["cwd"]))

    def test_model_configurable(self):
        runner = FakeRunner(agent_message(GOOD))
        SubscriptionBackend(runner=runner, model="m-x").classify(DifficultyInput("t"), 1)
        cmd = runner.calls[0]["cmd"]
        self.assertEqual(cmd[cmd.index("-m") + 1], "m-x")


class PromptTest(unittest.TestCase):
    def test_contains_task_paths_and_levels(self):
        p = build_prompt(DifficultyInput(task="Add X", paths=("a.py", "b.py"), repo_summary="small"))
        for needle in ("Add X", "a.py", "b.py", "small", "implementation", "xhigh", "JSON"):
            self.assertIn(needle, p)

    def test_session_context_is_included_only_when_present(self):
        with_ctx = build_prompt(DifficultyInput(task="진행", context="Session summary:\nplan X"))
        self.assertLess(with_ctx.index("plan X"), with_ctx.index("Task:\n진행"))
        self.assertNotIn("Session context", build_prompt(DifficultyInput(task="진행")))

    VERIFIED = staticmethod(lambda: "0.160.1")

    def test_both_classifiers_get_session_context_on_stdin_only(self):
        task = DifficultyInput("진행", context="Session summary:\nPLAN CONTEXT MARKER")
        codex = FakeRunner(agent_message(GOOD))
        SubscriptionBackend(runner=codex, host="codex", version_probe=self.VERIFIED).classify(task, 5)
        claude = FakeRunner(json.dumps({"type": "result", "is_error": False, "session_id": "x", "result": GOOD,
                                        "usage": {"input_tokens": 1, "output_tokens": 1}}))
        SubscriptionBackend(runner=claude, host="claude").classify(task, 5)
        for runner in (codex, claude):
            call = runner.calls[0]
            self.assertIn("PLAN CONTEXT MARKER", call["input_text"])
            self.assertNotIn("PLAN CONTEXT MARKER", " ".join(call["cmd"]))
        self.assertEqual(codex.calls[0]["cmd"][-1], "-")
        self.assertEqual(claude.calls[0]["cmd"][-1], "--no-session-persistence")

    def test_verified_codex_classifier_runs_with_the_tool_free_flags_between_sandbox_and_model(self):
        from model_effort_router.difficulty.subscription import CODEX_TOOLLESS_FLAGS
        self.assertIsInstance(CODEX_TOOLLESS_FLAGS, tuple)
        runner = FakeRunner(agent_message(GOOD))
        SubscriptionBackend(runner=runner, host="codex", version_probe=self.VERIFIED).classify(DifficultyInput("x"), 5)
        cmd = runner.calls[0]["cmd"]
        self.assertEqual(cmd.count("--disable"), 14)
        self.assertIn('web_search="disabled"', cmd)
        start = cmd.index(CODEX_TOOLLESS_FLAGS[0])
        self.assertEqual(tuple(cmd[start:start + len(CODEX_TOOLLESS_FLAGS)]), CODEX_TOOLLESS_FLAGS)
        self.assertEqual(cmd[start - 2:start], ["-s", "read-only"])
        self.assertEqual(cmd[start + len(CODEX_TOOLLESS_FLAGS)], "-m")
        self.assertEqual(cmd[-1], "-")

    def test_unverified_codex_gets_neither_locked_flags_nor_session_context(self):
        task = DifficultyInput("진행", context="Session summary:\nPLAN CONTEXT MARKER")
        for version in ("0.159.9", "0.161.0", None):
            runner = FakeRunner(agent_message(GOOD))
            with self.subTest(version=version):
                SubscriptionBackend(runner=runner, host="codex", version_probe=lambda: version).classify(task, 5)
                call = runner.calls[0]
                self.assertNotIn("--disable", call["cmd"])
                self.assertNotIn('web_search="disabled"', call["cmd"])
                self.assertNotIn("PLAN CONTEXT MARKER", call["input_text"])
                self.assertIn("진행", call["input_text"])
                self.assertEqual(call["cmd"][-1], "-")
                self.assertIn(["-s", "read-only"], [call["cmd"][i:i + 2] for i in range(len(call["cmd"]) - 1)])

    def test_codex_version_probe_parses_caches_and_fails_closed(self):
        from model_effort_router.difficulty import subscription as sub
        def run(stdout="", exc=None):
            def fake(*a, **k):
                if exc:
                    raise exc
                return subprocess.CompletedProcess(a, 0, stdout, "")
            return fake
        cases = [("codex-cli 0.160.1\n", None, "0.160.1"), ("garbage", None, None), ("", None, None),
                 ("", subprocess.TimeoutExpired("codex", 3), None), ("", OSError("gone"), None)]
        for stdout, exc, want in cases:
            sub._probe_version.cache_clear()
            with self.subTest(stdout=stdout, exc=exc), mock.patch.object(sub.subprocess, "run", run(stdout, exc)):
                self.assertEqual(sub._probe_version("/bin/codex", 1.0), want)
        sub._probe_version.cache_clear()
        calls = []
        with mock.patch.object(sub.subprocess, "run", lambda *a, **k: calls.append(1) or subprocess.CompletedProcess(a, 0, "codex-cli 0.160.1", "")):
            sub._probe_version("/bin/codex", 1.0)
            sub._probe_version("/bin/codex", 1.0)
            sub._probe_version("/bin/codex", 2.0)  # the binary changed: probe again
        self.assertEqual(len(calls), 2)
        sub._probe_version.cache_clear()
        with mock.patch.object(sub.shutil, "which", return_value=None):
            self.assertIsNone(sub.codex_version())
        self.assertEqual(sub.VERIFIED_CODEX_VERSIONS, ("0.160.1",))

    def test_default_runner_feeds_input_text_to_stdin(self):
        out = default_runner(["cat"], stdin=subprocess.DEVNULL, env=os.environ, timeout_s=5, cwd=None, input_text="한글 prompt")
        self.assertEqual(out, "한글 prompt")

    def test_isolated_argv_without_a_prompt_leaves_it_for_stdin(self):
        from model_effort_router.difficulty.subscription import isolated_argv
        argv = isolated_argv("claude", None)
        self.assertEqual(argv[-1], "--no-session-persistence")
        self.assertNotIn("--", argv)

    def test_task_is_truncated(self):
        p = build_prompt(DifficultyInput(task="x" * (MAX_TASK_CHARS * 3)))
        self.assertLess(len(p), MAX_TASK_CHARS * 2)


class DefaultRunnerTest(unittest.TestCase):
    """Uses the current Python interpreter, never codex."""

    def run_py(self, code, timeout_s=10, cwd=None):
        return default_runner(
            [sys.executable, "-c", code],
            stdin=subprocess.DEVNULL,
            env=dict(os.environ),
            timeout_s=timeout_s,
            cwd=cwd or os.getcwd(),
        )

    def test_returns_stdout(self):
        self.assertEqual(self.run_py("print('hi')").strip(), "hi")

    def test_timeout_becomes_timeout_error(self):
        with self.assertRaises(TimeoutError):
            self.run_py("import time; time.sleep(5)", timeout_s=0.2)

    def test_nonzero_exit_raises(self):
        with self.assertRaises(RuntimeError):
            self.run_py("import sys; sys.exit(3)")

    def test_failure_message_prefers_stderr(self):
        with self.assertRaisesRegex(RuntimeError, r"exited 3: boom"):
            self.run_py("import sys; sys.stderr.write('boom'); sys.exit(3)")

    def test_failure_message_uses_the_json_result_when_stderr_is_empty(self):
        # claude -p --output-format json reports errors on stdout, after a long usage blob
        code = ("import json, sys; print(json.dumps({'is_error': True, 'usage': {'pad': 'x' * 500}, "
                "'result': 'Failed to authenticate: OAuth session expired'})); sys.exit(1)")
        with self.assertRaisesRegex(CliAuthError, r"exited 1: Failed to authenticate"):
            self.run_py(code)

    def test_auth_failures_raise_cli_auth_error(self):
        for code in ("import sys; sys.stderr.write('Error: Not logged in. Please run claude auth login'); sys.exit(1)",
                     "import sys; sys.stderr.write('401 Unauthorized'); sys.exit(1)"):
            with self.assertRaises(CliAuthError):
                self.run_py(code)
        with self.assertRaises(RuntimeError) as ctx:
            self.run_py("import sys; sys.stderr.write('boom'); sys.exit(3)")
        self.assertNotIsInstance(ctx.exception, CliAuthError)

    def test_failure_message_uses_the_json_subtype_when_there_is_no_result(self):
        code = "import json, sys; print(json.dumps({'is_error': True, 'subtype': 'error_max_turns'})); sys.exit(1)"
        with self.assertRaisesRegex(RuntimeError, r"exited 1: error_max_turns"):
            self.run_py(code)

    def test_non_json_stdout_is_never_echoed_into_the_error(self):
        # codex streams JSONL events that can hold file contents; only parsed JSON results are surfaced
        with self.assertRaises(RuntimeError) as ctx:
            self.run_py("import sys; print('SECRET=hunter2'); sys.exit(2)")
        self.assertEqual(str(ctx.exception), "classifier exited 2: (no stderr)")

    def test_cwd_is_honored(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.run_py("import os; print(os.getcwd())", cwd=d).strip()
            self.assertEqual(os.path.realpath(out), os.path.realpath(d))

    def test_timeout_kills_grandchildren(self):
        with tempfile.TemporaryDirectory() as d:
            pidfile = os.path.join(d, "pid")
            code = (
                "import subprocess, sys, time\n"
                "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
                f"open({pidfile!r}, 'w').write(str(g.pid))\n"
                "time.sleep(30)\n"
            )
            with self.assertRaises(TimeoutError):
                self.run_py(code, timeout_s=1.5)
            with open(pidfile) as fh:
                pid = int(fh.read())
            for _ in range(50):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    return
                time.sleep(0.1)
            os.kill(pid, 9)
            self.fail("grandchild survived the timeout")

    def test_stdin_is_devnull(self):
        self.assertEqual(self.run_py("import sys; print(repr(sys.stdin.read()))").strip(), "''")


if __name__ == "__main__":
    unittest.main()

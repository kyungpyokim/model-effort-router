import io
import json
import math
import pathlib
import subprocess
import tempfile
import unittest
import time
import os
import signal
from types import SimpleNamespace
from unittest.mock import patch

from model_effort_router.cli import main
from model_effort_router.difficulty.chain import ClassificationError, classify_with_fallback
from model_effort_router.difficulty.decision import DifficultyDecision, ROLES
from model_effort_router.flow import ModelUnavailableBeforeExecution, WorkerFallbackError, run_worker
from model_effort_router.host import hosts
from model_effort_router.host.codex_hooks import main as hook_main
from model_effort_router.policy.config import resolve_config
from model_effort_router.policy.overrides import parse_override
from model_effort_router.policy.router import RoutePlan, route
from model_effort_router.policy.targeting import classify_target, NO_ROUTE, ROUTE
from model_effort_router.difficulty.subscription import DifficultyInput, SubscriptionBackend, build_prompt


class Backend:
    def __init__(self, name, result=None, error=None):
        self.name, self.result, self.error = name, result, error
        self.calls_model = False
        self.last_usage = None

    def classify(self, _task, _timeout):
        if self.error:
            raise self.error
        return self.result


class RouteContractTests(unittest.TestCase):
    def test_classifier_contract_requires_role_effort_and_rejects_bad_confidence(self):
        self.assertEqual(len(ROLES), 8)
        self.assertEqual(DifficultyDecision("implementation", "high", "fake", .9).effort, "high")
        for value in (True, math.nan, math.inf, -0.1, 1.1):
            with self.subTest(confidence=value), self.assertRaises(ValueError):
                DifficultyDecision("review", "high", "fake", value)
        for role, effort in (("L3", "high"), ("review", "L4")):
            with self.subTest(role=role, effort=effort), self.assertRaises(ValueError):
                DifficultyDecision(role, effort, "fake")

    def test_classifier_fallback_and_exhaustion_never_invent_a_role(self):
        result = DifficultyDecision("analysis", "medium", "second")
        got, causes = classify_with_fallback(None, [Backend("first", error=TimeoutError()), Backend("second", result)], 1)
        self.assertEqual((got, causes), (result, ("first:TimeoutError",)))
        with self.assertRaises(ClassificationError):
            classify_with_fallback(None, [Backend("bad", error=ValueError())], 1)

    def test_primary_and_fallback_model_mapping_and_explicit_phase(self):
        cfg = {"models": {"codex": {"execution": {"primary": "exec-primary", "fallback": "exec-fallback"}}}}
        plan = route("already approved implementation", repo_config=cfg, role_override="implementation",
                     effort_override="high", explicit=True)
        self.assertEqual((plan.model, plan.fallback_model, plan.agent, plan.applied_effort),
                         ("exec-primary", "exec-fallback", "execution", "high"))

    def test_role_override_bypasses_targeting_and_manual_mode_without_classifier(self):
        cfg = {"router": {"mode": "manual"}, "difficulty": {"backend": "none", "fallback": "none"}}
        plan = route("Please help me think about the architecture", repo_config=cfg,
                     role_override="analysis", effort_override="high")
        self.assertEqual((plan.target, plan.decision.role, plan.agent), (ROUTE, "analysis", "reasoning"))

    def test_explicit_classifier_override_has_no_classifier_usage_or_fallback_accounting(self):
        cfg = {"difficulty": {"backend": "first", "fallback": "second"}}
        plan = route("What is the capital of France?", repo_config=cfg, registry={
            "first": lambda: Backend("first", error=AssertionError("must not be called")),
            "second": lambda: Backend("second", error=AssertionError("must not be called")),
        }, role_override="analysis", effort_override="medium")
        self.assertIsNone(plan.classifier_usage)
        self.assertFalse(plan.classifier_usage_missing)
        from model_effort_router.logging.route_log import route_event
        event = route_event(plan, latency_ms=0, prompt="p", configured_backend="first")
        self.assertNotIn("classifier_fallback", event)
        self.assertNotIn("classifier_usage", event)

    def test_risk_floor_raises_effort_without_changing_role_or_lane(self):
        plan = route("review authentication security changes", explicit=True,
                     role_override="review", effort_override="low")
        self.assertEqual((plan.agent, plan.requested_effort, plan.applied_effort), ("reasoning", "low", "high"))
        self.assertIn("security", plan.risk_flags)

    def test_explicit_opencode_route_detects_korean_auth_and_payment_risks(self):
        plan = route("인증/결제 신뢰경계 검토", role_override="review", effort_override="medium",
                     host="opencode")
        self.assertEqual(plan.risk_flags, ("auth", "payment"))

    def test_no_route_policy_still_routes_code_analysis_and_design(self):
        self.assertEqual(classify_target("Why does parser.py fail?"), ROUTE)
        self.assertEqual(classify_target("Analyze the cause of race condition in worker.py"), ROUTE)
        self.assertEqual(classify_target("What is the capital of France?"), NO_ROUTE)

    def test_legacy_configuration_and_nimble_jev_give_migration_errors(self):
        with self.assertRaisesRegex(ValueError, "session/profile"):
            resolve_config(repo={"session": {"default": "frontier"}})
        with self.assertRaisesRegex(ValueError, "nimble_jev.*removed"):
            resolve_config(repo={"difficulty": {"backend": "nimble_jev"}})
        from model_effort_router.difficulty.registry import create
        with self.assertRaisesRegex(ValueError, "was removed"):
            create("nimble_jev")

    def test_phase_override_parser_rejects_old_tier_syntax(self):
        parsed, task = parse_override("/router role=review effort=high\ninspect diff")
        self.assertEqual((parsed.role, parsed.effort, task), ("review", "high", "inspect diff"))
        self.assertTrue(parse_override("/router session=frontier:high")[0].rejected)


class WorkerSafetyTests(unittest.TestCase):
    def _plan(self, role="implementation"):
        return route("run selected worker", explicit=True, role_override=role, effort_override="high")

    @patch("model_effort_router.host.codex_exec.parse_stream", return_value=SimpleNamespace(text="done", thread_id="t", usage=None))
    def test_selected_model_and_effort_reach_host_argv(self, _parse):
        calls = []
        def runner(argv, **_kwargs):
            calls.append(argv)
            return "stream"
        plan = self._plan()
        result = run_worker("task", plan, cwd="/tmp", runner=runner, env={}, host=hosts.CODEX, timeout_s=3)
        self.assertIn("gpt-6-luna", calls[0])
        self.assertIn("model_reasoning_effort=high", calls[0])
        self.assertEqual(result["model"], "gpt-6-luna")

    def test_antigravity_route_uses_effort_suffixed_model_slug(self):
        plan = route("Fix parser.py", host="antigravity", explicit=True,
                     role_override="fix", effort_override="medium")
        self.assertEqual(plan.model, "gemini-3.8-flash-medium")

    def test_review_packet_includes_untracked_paths(self):
        from model_effort_router.cli import _context_packet
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(["git", "init", "-q"], cwd=directory, check=True)
            (pathlib.Path(directory) / "new_review_target.py").write_text("print('new')")
            packet = json.loads(_context_packet("Review new file", directory, self._plan("review")))
        self.assertIn("new_review_target.py", packet["diff"])

    def test_cli_sigterm_stops_spawned_worker_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            pidfile = root / "worker.pid"
            fake = fake_bin / "codex"
            fake.write_text(f"#!{os.sys.executable}\nimport os, time\nopen({str(pidfile)!r}, 'w').write(str(os.getpid()))\nwhile True: time.sleep(.1)\n")
            fake.chmod(0o755)
            env = {**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}", "PYTHONPATH": str(pathlib.Path(__file__).resolve().parents[1]),
                   "MER_CORE_PATH": str(pathlib.Path(__file__).resolve().parents[1]), "MER_STATE_DIR": str(root / "state"),
                   "HOME": str(root)}
            proc = subprocess.Popen([os.sys.executable, "-m", "model_effort_router.cli", "run", "--role", "fix",
                                     "--effort", "high", "--cwd", str(root), "Do work"], cwd=root, env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                for _ in range(100):
                    if pidfile.exists():
                        break
                    if proc.poll() is not None:
                        self.fail(f"CLI exited before starting worker: {proc.stderr.read()}")
                    time.sleep(.05)
                self.assertTrue(pidfile.exists(), "worker did not start")
                worker_pid = int(pidfile.read_text())
                proc.send_signal(signal.SIGTERM)
                proc.communicate(timeout=8)
                self.assertNotEqual(proc.returncode, 0)
                for _ in range(60):
                    try:
                        os.kill(worker_pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(.05)
                else:
                    self.fail("worker survived CLI SIGTERM")
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()

    def test_cli_sigterm_stops_classifier_and_does_not_retry_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / ".model-effort-router.json").write_text(json.dumps(
                {"difficulty": {"backend": "subscription", "fallback": "subscription"}}))
            fake_bin = root / "bin"
            fake_bin.mkdir()
            pidfile, countfile = root / "classifier.pid", root / "calls"
            fake = fake_bin / "codex"
            fake.write_text(
                f"#!{os.sys.executable}\nimport os, time\np={str(countfile)!r}\n"
                "with open(p, 'a') as f: f.write('call\\n')\n"
                f"open({str(pidfile)!r}, 'w').write(str(os.getpid()))\n"
                "while True: time.sleep(.1)\n")
            fake.chmod(0o755)
            env = {**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}",
                   "PYTHONPATH": str(pathlib.Path(__file__).resolve().parents[1]),
                   "MER_CORE_PATH": str(pathlib.Path(__file__).resolve().parents[1]),
                   "MER_STATE_DIR": str(root / "state"), "HOME": str(root)}
            proc = subprocess.Popen([os.sys.executable, "-m", "model_effort_router.cli", "route", "--json",
                                     "--cwd", str(root), "Fix parser.py"], cwd=root, env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                for _ in range(100):
                    if pidfile.exists():
                        break
                    if proc.poll() is not None:
                        self.fail(f"CLI exited before starting classifier: {proc.stderr.read()}")
                    time.sleep(.05)
                self.assertTrue(pidfile.exists(), "classifier did not start")
                classifier_pid = int(pidfile.read_text())
                proc.send_signal(signal.SIGTERM)
                proc.communicate(timeout=8)
                self.assertNotEqual(proc.returncode, 0)
                self.assertEqual(countfile.read_text().splitlines(), ["call"], "SIGTERM retried classifier")
                for _ in range(60):
                    try:
                        os.kill(classifier_pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(.05)
                else:
                    self.fail("classifier survived CLI SIGTERM")
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()

    def test_run_log_records_actual_model_fallback_status_and_usage(self):
        from unittest.mock import patch
        import model_effort_router.cli as cli
        with tempfile.TemporaryDirectory() as directory:
            events = []
            worker = {"model": "backup-model", "fallback_reason": "ModelUnavailableBeforeExecution",
                      "usage": {"input": 11, "output": 2}, "message": "done"}
            with patch.object(cli, "run_worker", return_value=worker), patch.object(cli.route_log, "append",
                                                                                      side_effect=lambda _d, _s, ev: events.append(ev)):
                status = cli.main(["run", "--role", "fix", "--effort", "high", "--json", "--cwd", directory,
                                   "Fix parser.py"], env={"HOME": directory, "MER_STATE_DIR": str(pathlib.Path(directory) / "state")},
                                  out=io.StringIO())
        event = events[0]
        self.assertEqual(status, 0)
        self.assertEqual((event["requested_model"], event["actual_model"], event["fallback_reason"], event["status"], event["usage"]),
                         ("gpt-6-luna", "backup-model", "ModelUnavailableBeforeExecution", "complete", {"input": 11, "output": 2}))

    def test_cancellation_during_fallback_logs_actual_model_and_primary_rejection(self):
        import threading
        import model_effort_router.cli as cli
        from model_effort_router.flow import run_worker as execute_worker
        plan = self._plan()
        plan = plan.__class__(**{**plan.__dict__, "fallback_model": "gpt-6.1-sol"})
        events, calls = [], []

        def run_with_signal(task, selected_plan, **kwargs):
            kwargs.pop("runner")
            def runner(argv, **_runner_kwargs):
                calls.append(argv)
                if len(calls) == 1:
                    raise ModelUnavailableBeforeExecution("primary unavailable")
                threading.Timer(.1, os.kill, args=(os.getpid(), signal.SIGTERM)).start()
                while True:
                    time.sleep(.01)
            return execute_worker(task, selected_plan, runner=runner, **kwargs)

        with patch.object(cli, "route", return_value=plan), patch.object(cli, "run_worker", side_effect=run_with_signal), \
                patch.object(cli.route_log, "append", side_effect=lambda _d, _s, event: events.append(event)):
            status = cli.main(["run", "--role", "fix", "--effort", "high", "--json", "Fix parser.py"],
                              env={"HOME": "/nonexistent", "MER_STATE_DIR": "/tmp/mer-test-state"}, out=io.StringIO())
        self.assertEqual(status, 1)
        self.assertEqual(len(calls), 2, "cancellation retried the fallback worker")
        event = events[0]
        self.assertEqual((event["actual_model"], event["fallback_reason"], event["status"]),
                         ("gpt-6.1-sol", "ModelUnavailableBeforeExecution", "error"))

    @patch("model_effort_router.host.codex_exec.parse_stream", return_value=SimpleNamespace(text="done", thread_id="t", usage=None))
    def test_only_explicit_preexecution_unavailable_retries_once(self, _parse):
        plan = self._plan()
        plan = plan.__class__(**{**plan.__dict__, "fallback_model": "gpt-6.1-sol"})
        calls = []
        def runner(argv, **_kwargs):
            calls.append(argv)
            if len(calls) == 1:
                raise ModelUnavailableBeforeExecution("model unavailable before start")
            return "stream"
        result = run_worker("task", plan, cwd="/tmp", runner=runner, env={}, host=hosts.CODEX, timeout_s=3)
        self.assertEqual(len(calls), 2)
        self.assertIn("gpt-6.1-sol", calls[1])
        self.assertEqual(result["model"], "gpt-6.1-sol")

    @patch("model_effort_router.host.codex_exec.parse_stream", return_value=SimpleNamespace(text="done", thread_id="t", usage=None))
    def test_timeout_or_generic_error_does_not_retry(self, _parse):
        plan = self._plan()
        calls = []
        def runner(argv, **_kwargs):
            calls.append(argv)
            raise TimeoutError("uncertain whether work started")
        with self.assertRaises(TimeoutError):
            run_worker("task", plan, cwd="/tmp", runner=runner, env={}, host=hosts.CODEX, timeout_s=3)
        self.assertEqual(len(calls), 1)

    @patch("model_effort_router.host.codex_exec.parse_stream", return_value=SimpleNamespace(text="done", thread_id="t", usage=None))
    def test_failed_fallback_preserves_actual_model_and_primary_rejection_reason(self, _parse):
        plan = self._plan()
        plan = plan.__class__(**{**plan.__dict__, "fallback_model": "gpt-6.1-sol"})
        calls = iter((ModelUnavailableBeforeExecution("primary unavailable"), TimeoutError("fallback timed out")))
        with self.assertRaises(WorkerFallbackError) as ctx:
            run_worker("task", plan, cwd="/tmp", runner=lambda *_a, **_kw: (_ for _ in ()).throw(next(calls)),
                       env={}, host=hosts.CODEX, timeout_s=3)
        self.assertEqual((ctx.exception.model, ctx.exception.fallback_reason),
                         ("gpt-6.1-sol", "ModelUnavailableBeforeExecution"))

    @patch("model_effort_router.host.codex_exec.parse_stream", return_value=SimpleNamespace(text="", thread_id="t", usage=None))
    def test_invalid_fallback_stream_preserves_actual_model_and_primary_rejection_reason(self, _parse):
        plan = self._plan()
        plan = plan.__class__(**{**plan.__dict__, "fallback_model": "gpt-6.1-sol"})
        calls = iter((ModelUnavailableBeforeExecution("primary unavailable"), "{}"))
        def runner(*_args, **_kwargs):
            result = next(calls)
            if isinstance(result, BaseException):
                raise result
            return result
        with self.assertRaises(WorkerFallbackError) as ctx:
            run_worker("task", plan, cwd="/tmp", runner=runner, env={}, host=hosts.CODEX, timeout_s=3)
        self.assertEqual((ctx.exception.model, ctx.exception.fallback_reason),
                         ("gpt-6.1-sol", "ModelUnavailableBeforeExecution"))
        self.assertIsInstance(ctx.exception.__cause__, RuntimeError)

    @patch("model_effort_router.host.codex_exec.parse_stream", return_value=SimpleNamespace(text="review", thread_id="t", usage=None))
    def test_reasoning_roles_use_readonly_sandbox_and_antigravity_is_rejected(self, _parse):
        calls = []
        plan = self._plan("review")
        run_worker("review", plan, cwd="/tmp", runner=lambda argv, **_kw: calls.append(argv) or "stream",
                   env={}, host=hosts.CODEX, timeout_s=3)
        self.assertIn("read-only", calls[0])
        with self.assertRaisesRegex(ValueError, "unsupported"):
            run_worker("task", plan, cwd="/tmp", runner=lambda *_a, **_k: None, env={}, host=hosts.ANTIGRAVITY, timeout_s=3)


class CliAndHookTests(unittest.TestCase):
    def test_cli_route_json_is_mapping_only_and_explicit_override_needs_both_fields(self):
        out = io.StringIO()
        status = main(["route", "--host", "codex", "--role", "test", "--effort", "medium", "--json", "Run tests"],
                      env={"HOME": "/nonexistent"}, out=out)
        payload = json.loads(out.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual((payload["role"], payload["agent"], payload["effort"]), ("test", "execution", "medium"))
        self.assertEqual(main(["route", "--role", "test", "Run tests"], env={"HOME": "/nonexistent"}, out=io.StringIO()), 2)

    def test_cli_passes_active_project_name_from_cwd_to_the_router(self):
        with tempfile.TemporaryDirectory(prefix="router-project-") as cwd:
            with patch("model_effort_router.cli.route", return_value=RoutePlan(NO_ROUTE, "auto")) as routed:
                status = main(["route", "--automatic", "--json", "--cwd", cwd, "현재 진행 상황 파악"],
                              env={"HOME": "/nonexistent"}, out=io.StringIO())
        self.assertEqual(status, 0)
        self.assertEqual(routed.call_args.kwargs["repo_summary"], pathlib.Path(cwd).name)

    def test_hook_is_fail_open_on_classifier_failure_and_advisory_only(self):
        out = io.StringIO()
        env = {"MER_USER_CONFIG": "/nonexistent", "HOME": "/nonexistent"}
        with patch("model_effort_router.host.codex_hooks.route", side_effect=ClassificationError("provider chain exhausted")):
            self.assertEqual(hook_main("UserPromptSubmit", "/plugin", stdin=io.StringIO(json.dumps(
                {"session_id": "s", "cwd": "/tmp", "prompt": "Fix parser.py"})), stdout=out, env=env), 0)
        self.assertEqual(out.getvalue(), "")
        # The route advice has no host-setting mutation command and does not execute a Subagent.
        plan = route("fix parser.py", explicit=True, role_override="fix", effort_override="medium")
        from model_effort_router.host.advice import render
        advice = render(plan, "mer", hosts.CODEX)
        self.assertIn("does not change this Main turn", advice)
        self.assertNotIn("turn/settings/update", advice)

    def test_cli_automatic_route_reports_no_route_even_when_the_classifier_decided_it(self):
        decision = DifficultyDecision("analysis", "low", "jev", target="no_route")
        out = io.StringIO()
        with patch("model_effort_router.cli.route", return_value=RoutePlan(NO_ROUTE, "auto", decision)):
            status = main(["route", "--automatic", "--json", "승인"], env={"HOME": "/nonexistent"}, out=out)
        self.assertEqual((status, json.loads(out.getvalue())), (0, {"route": "no_route"}))

    def test_chat_is_migration_error_and_does_not_start_a_session(self):
        self.assertEqual(main(["chat", "old flow"], env={}, out=io.StringIO()), 2)

    def test_subscription_classifier_uses_role_effort_prompt_and_injected_runner(self):
        seen = {}
        def runner(argv, **kwargs):
            seen.update(argv=argv, **kwargs)
            return '\n'.join((json.dumps({"type": "item.completed", "item": {"type": "agent_message",
                "text": '{"role":"analysis","effort":"high","confidence":0.8}'}}),
                json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 3}})))
        prompt = build_prompt(DifficultyInput("analyze parser.py", ("src/parser.py",)))
        self.assertIn('"role":"implementation","effort":"medium"', prompt)
        self.assertNotIn("L1", prompt)
        backend = SubscriptionBackend(runner=runner, host="codex")
        result = backend.classify(DifficultyInput("analyze parser.py", ("src/parser.py",)), 2)
        self.assertEqual((result.role, result.effort, result.confidence), ("analysis", "high", .8))
        self.assertIn("--ignore-user-config", seen["argv"])
        self.assertEqual(seen["env"]["MER_CLASSIFIER"], "1")

    def test_host_docs_and_manifests_describe_advisory_single_worker_contract(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        for host in ("codex", "claude", "antigravity"):
            skill = (root / "plugins" / f"{host}-model-effort-router" / "skills/classify/SKILL.md").read_text()
            readme = (root / "plugins" / f"{host}-model-effort-router/README.md").read_text()
            self.assertIn("role", skill.lower())
            self.assertIn("Context Packet", skill)
            if host == "antigravity":
                self.assertNotIn("L1-L5", skill)
                self.assertIn("mer run` is unsupported", skill)
            else:
                self.assertIn("L1-L5", skill)
                self.assertIn("removed", skill)
            self.assertNotIn("escalates the same session", readme)
            self.assertIn("never changes the current turn", (root / "plugins/codex-model-effort-router/skills/classify/SKILL.md").read_text())


if __name__ == "__main__":
    unittest.main()

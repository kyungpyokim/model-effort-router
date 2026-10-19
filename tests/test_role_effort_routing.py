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
from unittest.mock import patch

from model_effort_router.cli import main
from model_effort_router.difficulty.chain import ClassificationError, classify_with_fallback
from model_effort_router.difficulty.decision import DifficultyDecision, ROLES
from model_effort_router.host import hosts
from model_effort_router.host.advice import NO_ROUTE_MESSAGE
from model_effort_router.host.codex_hooks import main as hook_main
from model_effort_router.policy.config import resolve_config
from model_effort_router.policy.overrides import parse_override
from model_effort_router.policy.router import RoutePlan, route
from model_effort_router.policy.targeting import NO_ROUTE, ROUTE
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
        self.assertEqual(DifficultyDecision("implementation", "high", "fake", 0.9).effort, "high")
        for value in (True, math.nan, math.inf, -0.1, 1.1):
            with self.subTest(confidence=value), self.assertRaises(ValueError):
                DifficultyDecision("review", "high", "fake", value)
        for role, effort in (("L3", "high"), ("review", "L4")):
            with self.subTest(role=role, effort=effort), self.assertRaises(ValueError):
                DifficultyDecision(role, effort, "fake")

    def test_classifier_fallback_and_exhaustion_never_invent_a_role(self):
        result = DifficultyDecision("analysis", "medium", "second")
        got, causes = classify_with_fallback(
            None, [Backend("first", error=TimeoutError()), Backend("second", result)], 1
        )
        self.assertEqual((got, causes), (result, ("first:TimeoutError",)))
        with self.assertRaises(ClassificationError):
            classify_with_fallback(None, [Backend("bad", error=ValueError())], 1)

    def test_legacy_model_fallback_is_ignored_by_model_selection(self):
        cfg = {"models": {"codex": {"execution": {"primary": "exec-primary", "fallback": "exec-fallback"}}}}
        plan = route(
            "already approved implementation",
            repo_config=cfg,
            role_override="implementation",
            effort_override="high",
            explicit=True,
        )
        self.assertEqual(
            (plan.model, plan.agent, plan.applied_effort),
            ("exec-primary", "execution", "high"),
        )

    def test_role_override_bypasses_targeting_and_manual_mode_without_classifier(self):
        cfg = {"router": {"mode": "manual"}, "difficulty": {"backend": "none", "fallback": "none"}}
        plan = route(
            "Please help me think about the architecture",
            repo_config=cfg,
            role_override="analysis",
            effort_override="high",
        )
        self.assertEqual((plan.target, plan.decision.role, plan.agent), (ROUTE, "analysis", "reasoning"))

    def test_explicit_classifier_override_has_no_classifier_usage_or_fallback_accounting(self):
        cfg = {"difficulty": {"backend": "first", "fallback": "second"}}
        plan = route(
            "What is the capital of France?",
            repo_config=cfg,
            registry={
                "first": lambda: Backend("first", error=AssertionError("must not be called")),
                "second": lambda: Backend("second", error=AssertionError("must not be called")),
            },
            role_override="analysis",
            effort_override="medium",
        )
        self.assertIsNone(plan.classifier_usage)
        self.assertFalse(plan.classifier_usage_missing)
        from model_effort_router.logging.route_log import route_event

        event = route_event(plan, latency_ms=0, prompt="p", configured_backend="first")
        self.assertNotIn("classifier_fallback", event)
        self.assertNotIn("classifier_usage", event)

    def test_risk_floor_raises_effort_without_changing_role_or_lane(self):
        plan = route(
            "review authentication security changes", explicit=True, role_override="review", effort_override="low"
        )
        self.assertEqual((plan.agent, plan.requested_effort, plan.applied_effort), ("reasoning", "low", "high"))
        self.assertIn("security", plan.risk_flags)

    def test_explicit_opencode_route_detects_korean_auth_and_payment_risks(self):
        plan = route("인증/결제 신뢰경계 검토", role_override="review", effort_override="medium", host="opencode")
        self.assertEqual(plan.risk_flags, ("auth", "payment"))

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


class RoutingSafetyTests(unittest.TestCase):
    def test_antigravity_route_uses_effort_suffixed_model_slug(self):
        plan = route("Fix parser.py", host="antigravity", explicit=True, role_override="fix", effort_override="medium")
        self.assertEqual(plan.model, "gemini-3.8-flash-medium")

    def test_cli_sigterm_stops_classifier_and_does_not_retry_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / ".model-effort-router.json").write_text(
                json.dumps({"difficulty": {"backend": "subscription", "fallback": "subscription"}})
            )
            fake_bin = root / "bin"
            fake_bin.mkdir()
            pidfile, countfile = root / "classifier.pid", root / "calls"
            fake = fake_bin / "codex"
            fake.write_text(
                f"#!{os.sys.executable}\nimport os, time\np={str(countfile)!r}\n"
                "with open(p, 'a') as f: f.write('call\\n')\n"
                f"open({str(pidfile)!r}, 'w').write(str(os.getpid()))\n"
                "while True: time.sleep(.1)\n"
            )
            fake.chmod(0o755)
            env = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "PYTHONPATH": str(pathlib.Path(__file__).resolve().parents[1]),
                "MER_CORE_PATH": str(pathlib.Path(__file__).resolve().parents[1]),
                "MER_STATE_DIR": str(root / "state"),
                "HOME": str(root),
            }
            proc = subprocess.Popen(
                [
                    os.sys.executable,
                    "-m",
                    "model_effort_router.cli",
                    "route",
                    "--json",
                    "--cwd",
                    str(root),
                    "Fix parser.py",
                ],
                cwd=root,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                for _ in range(100):
                    if pidfile.exists():
                        break
                    if proc.poll() is not None:
                        self.fail(f"CLI exited before starting classifier: {proc.stderr.read()}")
                    time.sleep(0.05)
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
                    time.sleep(0.05)
                else:
                    self.fail("classifier survived CLI SIGTERM")
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()


class CliAndHookTests(unittest.TestCase):
    def test_cli_route_json_is_mapping_only_and_explicit_override_needs_both_fields(self):
        out = io.StringIO()
        status = main(
            ["route", "--host", "codex", "--role", "test", "--effort", "medium", "--json", "Run tests"],
            env={"HOME": "/nonexistent"},
            out=out,
        )
        payload = json.loads(out.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual((payload["role"], payload["agent"], payload["effort"]), ("test", "execution", "medium"))
        self.assertEqual(
            main(["route", "--role", "test", "Run tests"], env={"HOME": "/nonexistent"}, out=io.StringIO()), 2
        )

    def test_cli_passes_active_project_name_from_cwd_to_the_router(self):
        with tempfile.TemporaryDirectory(prefix="router-project-") as cwd:
            with patch("model_effort_router.cli.route", return_value=RoutePlan(NO_ROUTE, "auto")) as routed:
                status = main(
                    ["route", "--automatic", "--json", "--cwd", cwd, "현재 진행 상황 파악"],
                    env={"HOME": "/nonexistent"},
                    out=io.StringIO(),
                )
        self.assertEqual(status, 0)
        self.assertEqual(routed.call_args.kwargs["repo_summary"], pathlib.Path(cwd).name)

    def test_hook_is_fail_open_on_classifier_failure_and_advisory_only(self):
        out = io.StringIO()
        env = {"MER_USER_CONFIG": "/nonexistent", "HOME": "/nonexistent"}
        with patch(
            "model_effort_router.host.codex_hooks.route", side_effect=ClassificationError("provider chain exhausted")
        ):
            self.assertEqual(
                hook_main(
                    "UserPromptSubmit",
                    "/plugin",
                    stdin=io.StringIO(json.dumps({"session_id": "s", "cwd": "/tmp", "prompt": "Fix parser.py"})),
                    stdout=out,
                    env=env,
                ),
                0,
            )
        self.assertIn("classifier failed", out.getvalue())  # shown to the user; routing itself stays fail-open
        # The route advice has no host-setting mutation command and does not execute a Subagent.
        plan = route("fix parser.py", explicit=True, role_override="fix", effort_override="medium")
        from model_effort_router.host.advice import render

        advice = render(plan, hosts.CODEX)
        self.assertIn("does not change them", advice)
        self.assertNotIn("turn/settings/update", advice)

    def test_cli_automatic_route_reports_no_route_even_when_the_classifier_decided_it(self):
        decision = DifficultyDecision("analysis", "low", "jev", target="no_route")
        out = io.StringIO()
        with patch("model_effort_router.cli.route", return_value=RoutePlan(NO_ROUTE, "auto", decision)):
            status = main(["route", "--automatic", "--json", "승인"], env={"HOME": "/nonexistent"}, out=out)
        self.assertEqual(
            (status, json.loads(out.getvalue())),
            (
                0,
                {
                    "route": "no_route",
                    "mode": "auto",
                    "message": NO_ROUTE_MESSAGE,
                },
            ),
        )

    def test_chat_is_migration_error_and_does_not_start_a_session(self):
        self.assertEqual(main(["chat", "old flow"], env={}, out=io.StringIO()), 2)

    def test_subscription_classifier_uses_role_effort_prompt_and_injected_runner(self):
        seen = {}

        def runner(argv, **kwargs):
            seen.update(argv=argv, **kwargs)
            return "\n".join(
                (
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {
                                "type": "agent_message",
                                "text": '{"role":"analysis","effort":"high","confidence":0.8}',
                            },
                        }
                    ),
                    json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 3}}),
                )
            )

        prompt = build_prompt(DifficultyInput("analyze parser.py", ("src/parser.py",)))
        self.assertIn('"role":"implementation","effort":"medium"', prompt)
        self.assertNotIn("L1", prompt)
        backend = SubscriptionBackend(runner=runner, host="codex")
        result = backend.classify(DifficultyInput("analyze parser.py", ("src/parser.py",)), 2)
        self.assertEqual((result.role, result.effort, result.confidence), ("analysis", "high", 0.8))
        self.assertIn("--ignore-user-config", seen["argv"])
        self.assertEqual(seen["env"]["MER_CLASSIFIER"], "1")

    def test_host_docs_describe_model_selection_only(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        for host in ("codex", "claude", "antigravity"):
            skill = (root / "plugins" / f"{host}-model-effort-router" / "skills/classify/SKILL.md").read_text()
            readme = (root / "plugins" / f"{host}-model-effort-router/README.md").read_text()
            self.assertIn("role", skill.lower())
            self.assertIn("recommends", skill.lower())
            self.assertNotIn("Context Packet", skill)
            self.assertNotIn("L1-L5", skill)
            self.assertIn("mer route", skill)
            if host == "antigravity":
                self.assertIn("mer run` is no longer supported", skill)
            self.assertNotIn("escalates the same session", readme)
            self.assertIn(
                "does not change the active turn's settings",
                (root / "plugins/codex-model-effort-router/skills/classify/SKILL.md").read_text(),
            )


if __name__ == "__main__":
    unittest.main()

import io
import json
import unittest
from contextlib import redirect_stderr

from model_effort_router.cli import main
from model_effort_router.host import hosts
from model_effort_router.policy.config import resolve_config
from model_effort_router.policy.router import route


class OpenCodeHostTest(unittest.TestCase):
    def test_host_is_registered_and_has_route_advice_defaults(self):
        host = hosts.get("opencode", {})
        config = resolve_config()
        self.assertEqual(host.name, "opencode")
        self.assertEqual(config.models["opencode"]["execution"]["primary"], "openai/gpt-5.2")
        self.assertEqual(config.models["opencode"]["reasoning"]["primary"], "anthropic/claude-sonnet-4-5")

    def test_explicit_route_returns_opencode_advice_without_classifier(self):
        plan = route("Create an OpenCode plugin", host="opencode", explicit=True,
                     role_override="plan", effort_override="medium")
        self.assertEqual((plan.agent, plan.model, plan.applied_effort),
                         ("reasoning", "anthropic/claude-sonnet-4-5", "medium"))

    def test_worker_execution_is_rejected(self):
        result = io.StringIO()
        with redirect_stderr(result):
            status = main(["run", "--host", "opencode", "--role", "plan", "--effort", "medium", "Plan"],
                          env={"MER_TEST_FAKE_BACKEND": "{}"}, out=io.StringIO())
        self.assertEqual(status, 2)
        self.assertIn("OpenCode worker execution is unsupported", result.getvalue())


if __name__ == "__main__":
    unittest.main()

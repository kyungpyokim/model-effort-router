import unittest
from unittest import mock

from model_effort_router.difficulty import jev
from model_effort_router.difficulty.decision import DifficultyDecision, DifficultyInput
from model_effort_router.difficulty.nimble import DEFAULT_URL, NimbleBackend, check_local_url, validate_options
from model_effort_router.difficulty.registry import BACKENDS, create
from model_effort_router.policy.config import resolve_config
from model_effort_router.policy.router import route
from tests.test_jev import FakeTransport, response

TASK = "Fix the discount bug in pricing.py"


class NimbleProviderTest(unittest.TestCase):
    def test_local_classifier_uses_role_effort_contract_without_remote_credentials(self):
        transport = FakeTransport(response("fix", "high", usage={"input_tokens": 392, "output_tokens": 65}))
        backend = NimbleBackend(transport=transport, env={"TYPESAFE_API_KEY": "must-not-send"})
        decision = backend.classify(DifficultyInput(TASK, ("pricing.py",)), 7)
        url, headers, body, timeout = transport.calls[0]
        self.assertEqual((url, timeout), (DEFAULT_URL, 7))
        self.assertEqual(headers, {"Content-Type": "application/json"})
        self.assertEqual(set(body["questions"]), {"role", "effort"})
        self.assertIn(TASK, body["state"])
        self.assertNotIn("must-not-send", str(transport.calls))
        self.assertEqual((decision.role, decision.effort), ("fix", "high"))
        self.assertEqual(backend.last_usage, {"input_tokens": 392, "output_tokens": 65})

    def test_endpoint_and_model_precedence_and_loopback_validation(self):
        opts = {"model": "nimble:test", "url": "http://localhost:9999/v1/systemone"}
        env = {"MER_NIMBLE_MODEL": "ignored", "MER_NIMBLE_URL": "http://127.0.0.1:7777/v1/systemone"}
        t = FakeTransport()
        NimbleBackend(transport=t, env=env, options=opts).classify(DifficultyInput(TASK), 2)
        self.assertEqual((t.calls[0][0], t.calls[0][2]["model"]), (opts["url"], "nimble:test"))
        for url in ("https://api.typesafe.ai/v1/systemone", "http://example.com/x", "http://localhost.evil/x",
                    "http://user:pass@localhost/x", "file:///etc/passwd"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                check_local_url(url)

    def test_invalid_non_loopback_configuration_fails_before_transport(self):
        transport = FakeTransport()
        with self.assertRaises(ValueError):
            NimbleBackend(transport=transport, options={"url": "http://example.com/v1/systemone"})
        with self.assertRaises(ValueError):
            validate_options({"url": "https://api.typesafe.ai/v1/systemone"})
        self.assertEqual(transport.calls, [])

    def test_registry_and_config_keep_nimble_provider_swap_supported(self):
        self.assertIs(BACKENDS["nimble"], NimbleBackend)
        self.assertEqual(create("nimble", options={"model": "nimble:test"})._options["model"], "nimble:test")
        config = resolve_config(repo={"difficulty": {"backend": "nimble", "nimble": {"model": "nimble:test"}}},
                                registry={"nimble": NimbleBackend})
        self.assertEqual(config.nimble, {"model": "nimble:test"})
        with self.assertRaises(ValueError):
            resolve_config(repo={"difficulty": {"backend": "nimble_jev"}}, registry={"nimble": NimbleBackend})

    def test_provider_failure_uses_configured_classifier_fallback(self):
        transport = FakeTransport(exc=ConnectionRefusedError("refused"))
        local = NimbleBackend(transport=transport, env={})
        subscription = mock.Mock()
        subscription.name = "subscription"
        subscription.calls_model = True
        subscription.last_usage = None
        subscription.classify.return_value = DifficultyDecision("fix", "medium", "subscription")
        plan = route(TASK, repo_config={"difficulty": {"backend": "nimble", "fallback": "subscription"}},
                     registry={"nimble": lambda **kwargs: local, "subscription": lambda: subscription})
        self.assertEqual(plan.decision.backend, "subscription")
        subscription.classify.assert_called_once()

    def test_nimble_does_not_ask_for_or_provide_a_target(self):
        transport = FakeTransport(response(target="no_route"))
        decision = NimbleBackend(transport=transport, env={}).classify(DifficultyInput(TASK), 2)
        self.assertEqual((NimbleBackend.provides_target, decision.target), (False, None))

    def test_systemone_question_contract_matches_jev(self):
        self.assertEqual(set(jev.QUESTIONS), {"role", "effort"})


if __name__ == "__main__":
    unittest.main()

import json
import unittest

from model_effort_router.difficulty.decision import ROLES, DifficultyInput
from model_effort_router.difficulty import jev
from model_effort_router.difficulty.jev import (
    JevBackend,
    MissingKeyError,
    parse_decision,
)
from model_effort_router.difficulty.subscription import BackendOutputError
from model_effort_router.policy.config import resolve_config
from model_effort_router.policy.router import _make_backends


def response(role="fix", effort="medium", confidence=0.8, usage=None, target="route"):
    body = {
        "answers": {
            "role": {"choice": role, "confidence": confidence},
            "effort": {"choice": effort},
            "target": {"choice": target},
        }
    }
    if usage is not None:
        body["usage"] = usage
    return body


class FakeTransport:
    def __init__(self, body=None, status=200, exc=None):
        self.body, self.status, self.exc, self.calls = (
            body or response(),
            status,
            exc,
            [],
        )

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, json.loads(body), timeout))
        if self.exc:
            raise self.exc
        return self.status, json.dumps(self.body)


class JevContractTest(unittest.TestCase):
    def test_global_config_key_is_used_for_authorization(self):
        seen = {}

        def factory(**options):
            return JevBackend(
                transport=lambda url, headers, body, timeout: (
                    seen.update(headers=headers) or (200, json.dumps(response()))
                ),
                env={"TYPESAFE_API_KEY": "env-key"},
                **options,
            )

        backend = _make_backends(
            resolve_config(
                repo={"difficulty": {"backend": "jev"}},
                user={"jev": {"api_key": "global-key"}},
            ),
            {"jev": factory},
            {"jev": {"api_key": "global-key"}},
        )[0]
        backend.classify(DifficultyInput("x"), 1)
        self.assertEqual(seen["headers"]["Authorization"], "Bearer global-key")

    def test_environment_key_remains_fallback(self):
        seen = {}
        backend = JevBackend(
            transport=lambda url, headers, body, timeout: (
                seen.update(headers=headers) or (200, json.dumps(response()))
            ),
            env={"TYPESAFE_API_KEY": "env-key"},
        )
        backend.classify(DifficultyInput("x"), 1)
        self.assertEqual(seen["headers"]["Authorization"], "Bearer env-key")

    def test_repo_local_jev_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "global user config"):
            resolve_config(repo={"jev": {"api_key": "repo-key"}})

    def test_parser_accepts_role_effort_with_optional_metadata(self):
        got = parse_decision(
            {
                "role": "review",
                "effort": "xhigh",
                "confidence": 0.8,
                "reason_code": "security_review",
            },
            "jev",
        )
        self.assertEqual(
            (got.role, got.effort, got.confidence, got.reason_code),
            ("review", "xhigh", 0.8, "security_review"),
        )

    def test_invalid_or_legacy_level_output_is_rejected(self):
        for data in (
            {"level": "L3"},
            {"role": "review", "effort": "L4"},
            {"role": "unknown", "effort": "low"},
        ):
            with self.subTest(data=data), self.assertRaises(BackendOutputError):
                parse_decision(data, "jev")

    def test_classifier_requests_only_role_and_effort_and_uses_injected_transport(self):
        seen = {}

        def transport(url, headers, body, timeout):
            seen.update(body=json.loads(body), headers=headers, timeout=timeout)
            return 200, json.dumps(
                {
                    "answers": {
                        "role": {"choice": "analysis", "confidence": 0.7},
                        "effort": {"choice": "high"},
                        "target": {"choice": "route"},
                    }
                }
            )

        backend = JevBackend(transport=transport, env={"TYPESAFE_API_KEY": "test-key"})
        got = backend.classify(DifficultyInput("Analyze parser", ("src/parser.py",)), 4)
        self.assertEqual((got.role, got.effort), ("analysis", "high"))
        self.assertEqual(set(seen["body"]["questions"]), {"role", "effort", "target"})
        role = seen["body"]["questions"]["role"]
        self.assertEqual(set(role["criteria"]), set(ROLES))
        self.assertTrue(all(role["criteria"][name] != name for name in ROLES))
        self.assertIn("chat", role["criteria"]["analysis"].lower())
        self.assertIn("spelling", role["criteria"]["lint"].lower())
        effort = seen["body"]["questions"]["effort"]
        self.assertIn("independently of role", effort["instructions"])
        self.assertEqual(set(effort["criteria"]), {"low", "medium", "high", "xhigh", "max"})
        self.assertIn("approach", effort["criteria"]["low"].lower())
        self.assertIn("established patterns", effort["criteria"]["medium"].lower())
        self.assertIn("interacting", effort["criteria"]["high"].lower())
        self.assertIn("production data", effort["criteria"]["xhigh"].lower())
        self.assertIn("beyond xhigh", effort["criteria"]["max"].lower())
        self.assertEqual(seen["timeout"], 4)

    def test_target_question_and_answer_are_part_of_the_decision(self):
        t = FakeTransport(response("analysis", "low", target="no_route"))
        got = JevBackend(transport=t, env={"TYPESAFE_API_KEY": "k"}).classify(DifficultyInput("승인"), 3)
        self.assertEqual(got.target, "no_route")
        question = t.calls[0][2]["questions"]["target"]
        self.assertEqual((question["type"], set(question["criteria"])), ("choice", {"route", "no_route"}))
        self.assertIn("approvals", question["criteria"]["no_route"])
        self.assertTrue(JevBackend.provides_target)
        self.assertEqual(set(jev.QUESTIONS), {"role", "effort"})

    def test_missing_or_invalid_target_answer_is_a_backend_error(self):
        for answers in ({"role": {"choice": "fix"}, "effort": {"choice": "low"}},
                        {"role": {"choice": "fix"}, "effort": {"choice": "low"}, "target": {"choice": "maybe"}},
                        {"role": {"choice": "fix"}, "effort": {"choice": "low"}, "target": "route"}):
            backend = JevBackend(transport=FakeTransport({"answers": answers}), env={"TYPESAFE_API_KEY": "k"})
            with self.subTest(answers=answers), self.assertRaises(BackendOutputError):
                backend.classify(DifficultyInput("x"), 1)

    def test_missing_key_fails_for_provider_fallback(self):
        with self.assertRaises(MissingKeyError):
            JevBackend(env={}).classify(DifficultyInput("x"), 1)

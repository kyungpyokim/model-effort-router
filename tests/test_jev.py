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

    def test_target_contract_uses_requested_project_outcome_and_context(self):
        target = jev.TARGET_QUESTION
        route = target["criteria"]["route"].lower()
        no_route = target["criteria"]["no_route"].lower()
        self.assertIn("investigate", route)
        self.assertIn("analyze", route)
        self.assertIn("explain", route)
        self.assertIn("active project", route)
        self.assertIn("unrelated to software", no_route)
        self.assertIn("requested outcome", target["instructions"].lower())

    def test_session_context_precedes_the_current_request_in_the_state(self):
        t = FakeTransport(response("fix", "low"))
        backend = JevBackend(transport=t, env={"TYPESAFE_API_KEY": "k"})
        backend.classify(DifficultyInput("진행", ("a.py",), context="Session summary:\nplan X\n\nRecent turns:\n(none)"), 3)
        backend.classify(DifficultyInput("진행"), 3)
        with_ctx, without = (c[2]["state"] for c in t.calls)
        self.assertEqual(with_ctx, "Session context:\nSession summary:\nplan X\n\nRecent turns:\n(none)"
                                   "\n\nCurrent request:\n진행\n\nRelevant paths:\na.py")
        self.assertEqual(without, "Task:\n진행\n\nRelevant paths:\n(none)")

    def test_state_includes_repo_summary_without_workspace_path(self):
        state = jev.state_text(DifficultyInput("현재 진행 상황 파악", repo_summary="model-effort-router-next"))
        self.assertIn("Active project:\nmodel-effort-router-next", state)
        self.assertNotIn("/Users/", state)

    def test_state_bounds_repo_summary(self):
        state = jev.state_text(DifficultyInput("task", repo_summary="x" * (jev.MAX_TASK_CHARS * 2)))
        self.assertIn("Active project:\n" + "x" * jev.MAX_TASK_CHARS, state)
        self.assertNotIn("x" * (jev.MAX_TASK_CHARS + 1), state)

    def test_instructions_tie_followups_to_the_proposed_plan(self):
        t = FakeTransport(response("fix", "low"))
        JevBackend(transport=t, env={"TYPESAFE_API_KEY": "k"}).classify(DifficultyInput("x", context="c"), 3)
        questions = t.calls[0][2]["questions"]
        for name in ("role", "effort", "target"):
            text = questions[name]["instructions"].lower()
            self.assertIn("current request", text, name)
            self.assertIn("session context", text, name)
        target = questions["target"]
        self.assertIn("진행", target["criteria"]["route"])
        self.assertNotIn("진행", target["criteria"]["no_route"])
        no_route = target["criteria"]["no_route"]
        self.assertIn("승인", no_route)  # still an example, but only without a pending proposal
        self.assertIn("no pending proposal or plan", no_route)
        self.assertIn("nothing to execute", no_route)
        self.assertIn("approvals", target["criteria"]["no_route"])

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

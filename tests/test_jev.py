import json
import unittest
from model_effort_router.difficulty.decision import DifficultyInput
from model_effort_router.difficulty.jev import JevBackend, MissingKeyError, parse_decision
from model_effort_router.difficulty.subscription import BackendOutputError


def response(role="fix", effort="medium", confidence=0.8, usage=None):
    body = {"answers": {"role": {"choice": role, "confidence": confidence}, "effort": {"choice": effort}}}
    if usage is not None:
        body["usage"] = usage
    return body


class FakeTransport:
    def __init__(self, body=None, status=200, exc=None):
        self.body, self.status, self.exc, self.calls = body or response(), status, exc, []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, json.loads(body), timeout))
        if self.exc:
            raise self.exc
        return self.status, json.dumps(self.body)

class JevContractTest(unittest.TestCase):
    def test_parser_accepts_role_effort_with_optional_metadata(self):
        got=parse_decision({"role":"review","effort":"xhigh","confidence":0.8,"reason_code":"security_review"},"jev")
        self.assertEqual((got.role,got.effort,got.confidence,got.reason_code),("review","xhigh",.8,"security_review"))
    def test_invalid_or_legacy_level_output_is_rejected(self):
        for data in ({"level":"L3"},{"role":"review","effort":"L4"},{"role":"unknown","effort":"low"}):
            with self.subTest(data=data),self.assertRaises(BackendOutputError):
                parse_decision(data,"jev")
    def test_classifier_requests_only_role_and_effort_and_uses_injected_transport(self):
        seen={}
        def transport(url,headers,body,timeout):
            seen.update(body=json.loads(body),headers=headers,timeout=timeout)
            return 200,json.dumps({"answers":{"role":{"choice":"analysis","confidence":.7},"effort":{"choice":"high"}}})
        backend=JevBackend(transport=transport,env={"TYPESAFE_API_KEY":"test-key"})
        got=backend.classify(DifficultyInput("Analyze parser",("src/parser.py",)),4)
        self.assertEqual((got.role,got.effort),("analysis","high"))
        self.assertEqual(set(seen["body"]["questions"]),{"role","effort"})
        self.assertEqual(seen["timeout"],4)
    def test_missing_key_fails_for_provider_fallback(self):
        with self.assertRaises(MissingKeyError):
            JevBackend(env={}).classify(DifficultyInput("x"),1)

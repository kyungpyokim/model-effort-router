import unittest
from model_effort_router.difficulty.decision import DifficultyDecision
from model_effort_router.policy.router import route
from model_effort_router.policy.targeting import classify_target, ROUTE, NO_ROUTE

class FakeBackend:
    name = "fake"
    calls_model = False
    last_usage = None
    def __init__(self, role="implementation", effort="medium", error=None, target=None, name="fake", provides_target=False, usage=None):
        self.role,self.effort,self.error,self.target,self.name,self.provides_target=role,effort,error,target,name,provides_target
        self.calls, self.calls_model, self.last_usage = 0, usage is not None, usage
    def classify(self, task, timeout_s):
        self.calls += 1
        if self.error:
            raise self.error
        return DifficultyDecision(self.role, self.effort, self.name, target=self.target)

def registry(backend): return {"fake": lambda: backend}

class RouteTest(unittest.TestCase):
    def test_classifies_role_effort_and_maps_by_lane(self):
        b=FakeBackend("analysis","high")
        p=route("Analyze the parser bug",registry=registry(b),repo_config={"difficulty":{"backend":"fake"}})
        self.assertEqual((p.decision.role,p.decision.effort,p.agent,p.model),("analysis","high","reasoning","gpt-6.1-sol"))
    def test_explicit_role_effort_skips_classifier(self):
        p=route("plan next changes",role_override="plan",effort_override="medium",explicit=True)
        self.assertEqual((p.decision.role,p.agent),("plan","reasoning"))
    def test_safety_floor_only_raises_effort(self):
        p=route("review authentication security changes",role_override="review",effort_override="low",explicit=True)
        self.assertEqual((p.decision.role,p.agent,p.requested_effort,p.applied_effort),("review","reasoning","low","high"))
    def test_classifier_exhaustion_raises_instead_of_defaulting(self):
        with self.assertRaisesRegex(RuntimeError,"all classifiers failed"):
            route("Fix parser.py",registry=registry(FakeBackend(error=RuntimeError())),repo_config={"difficulty":{"backend":"fake"}})
    def test_targeting_includes_code_analysis_and_skips_chat(self):
        self.assertEqual(classify_target("Why does parser.py crash?"),ROUTE)
        self.assertEqual(classify_target("What is the capital of France?"),NO_ROUTE)


KOREAN = "원인 파악해"
CFG = {"difficulty": {"backend": "first", "fallback": "second"}}

class TargetFromBackendTest(unittest.TestCase):
    def plan(self, message, first, second=None):
        reg = {"first": lambda: first, "second": lambda: second or FakeBackend(name="second")}
        return route(message, registry=reg, repo_config=CFG)
    def test_backend_target_overrides_regex_gate_for_route(self):
        first, second = FakeBackend("fix", target="route", name="first", provides_target=True), FakeBackend(name="second")
        p = self.plan(KOREAN, first, second)
        self.assertEqual((p.target, p.decision.role, p.decision.backend, second.calls), (ROUTE, "fix", "first", 0))
        self.assertEqual(classify_target(KOREAN), NO_ROUTE)
    def test_backend_no_route_keeps_decision_without_model_mapping(self):
        p = self.plan("fix parser.py", FakeBackend(target="no_route", name="first", provides_target=True))
        self.assertEqual((p.target, p.decision.target, p.model, p.applied_effort), (NO_ROUTE, "no_route", None, None))
    def test_failed_target_backend_falls_back_to_regex_gate(self):
        first, second = FakeBackend(error=RuntimeError(), name="first", provides_target=True), FakeBackend(name="second")
        p = self.plan(KOREAN, first, second)
        self.assertEqual((p.target, p.decision, second.calls), (NO_ROUTE, None, 0))
        p = self.plan("Fix parser.py", FakeBackend(error=RuntimeError(), name="first", provides_target=True), second)
        self.assertEqual((p.target, p.decision.backend, second.calls), (ROUTE, "second", 1))
    def test_failed_target_backend_is_not_asked_twice(self):
        first = FakeBackend(error=RuntimeError(), name="first", provides_target=True)
        with self.assertRaisesRegex(RuntimeError, "all classifiers failed"):
            route("Fix parser.py", registry={"first": lambda: first, "second": lambda: FakeBackend(error=RuntimeError(), name="second")}, repo_config=CFG)
        self.assertEqual(first.calls, 1)
    def test_explicit_bypasses_backend_target(self):
        first = FakeBackend(target="no_route", name="first", provides_target=True)
        p = route(KOREAN, registry={"first": lambda: first}, repo_config={"difficulty": {"backend": "first", "fallback": "none"}}, explicit=True)
        self.assertEqual((p.target, p.decision.backend), (ROUTE, "first"))

    def test_target_backend_failure_without_fallback_follows_the_regex(self):
        cfg = {"difficulty": {"backend": "first", "fallback": "none"}}
        reg = {"first": lambda: FakeBackend(error=RuntimeError(), name="first", provides_target=True)}
        p = route(KOREAN, registry=reg, repo_config=cfg)
        self.assertEqual((p.target, p.decision), (NO_ROUTE, None))
        with self.assertRaisesRegex(RuntimeError, "all classifiers failed"):
            route("Fix parser.py", registry=reg, repo_config=cfg)
    def test_target_answers_from_fallback_slot_backends_are_ignored(self):
        first = FakeBackend(error=RuntimeError(), name="first")
        second = FakeBackend("fix", target="no_route", name="second", provides_target=True)
        p = self.plan("Fix parser.py", first, second)
        self.assertEqual((p.target, p.decision.backend, second.calls), (ROUTE, "second", 1))
        self.assertEqual(self.plan(KOREAN, FakeBackend(error=RuntimeError(), name="first"), second).decision, None)
    def test_regex_no_route_keeps_decision_and_usage_of_a_target_less_first_backend(self):
        usage = {"input_tokens": 5, "output_tokens": 1}
        p = self.plan(KOREAN, FakeBackend(name="first", provides_target=True, usage=usage))
        self.assertEqual((p.target, p.decision.backend, p.classifier_usage["input_tokens"]), (NO_ROUTE, "first", 5))
    def test_regex_no_route_keeps_usage_of_a_target_backend_that_failed(self):
        usage = {"input_tokens": 5, "output_tokens": 0}
        p = self.plan(KOREAN, FakeBackend(error=RuntimeError(), name="first", provides_target=True, usage=usage))
        self.assertEqual((p.target, p.decision, p.classifier_usage["input_tokens"]), (NO_ROUTE, None, 5))

import unittest
from model_effort_router.difficulty.decision import DifficultyDecision
from model_effort_router.policy.router import route
from model_effort_router.policy.targeting import classify_target, ROUTE, NO_ROUTE

class FakeBackend:
    name = "fake"
    calls_model = False
    last_usage = None
    def __init__(self, role="implementation", effort="medium", error=None): self.role,self.effort,self.error=role,effort,error
    def classify(self, task, timeout_s):
        if self.error:
            raise self.error
        return DifficultyDecision(self.role, self.effort, self.name)

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

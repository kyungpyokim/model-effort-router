import unittest
from model_effort_router.difficulty.decision import DifficultyDecision
from model_effort_router.policy.router import route
from model_effort_router.policy.targeting import ROUTE, NO_ROUTE


class FakeBackend:
    name = "fake"
    calls_model = False
    last_usage = None

    def __init__(
        self,
        role="implementation",
        effort="medium",
        error=None,
        target=None,
        name="fake",
        provides_target=False,
        usage=None,
    ):
        self.role, self.effort, self.error, self.target, self.name, self.provides_target = (
            role,
            effort,
            error,
            target,
            name,
            provides_target,
        )
        self.calls, self.calls_model, self.last_usage = 0, usage is not None, usage
        self.last_task = None

    def classify(self, task, timeout_s):
        self.calls += 1
        self.last_task = task
        if self.error:
            raise self.error
        return DifficultyDecision(self.role, self.effort, self.name, target=self.target)


def registry(backend):
    return {"fake": lambda: backend}


class RouteTest(unittest.TestCase):
    def test_classifies_role_effort_and_maps_by_lane(self):
        b = FakeBackend("analysis", "high")
        p = route("Analyze the parser bug", registry=registry(b), repo_config={"difficulty": {"backend": "fake"}})
        self.assertEqual(
            (p.decision.role, p.decision.effort, p.agent, p.model), ("analysis", "high", "reasoning", "gpt-6.1-sol")
        )

    def test_explicit_role_effort_skips_classifier(self):
        p = route("plan next changes", role_override="plan", effort_override="medium", explicit=True)
        self.assertEqual((p.decision.role, p.agent), ("plan", "reasoning"))

    def test_safety_floor_only_raises_effort(self):
        p = route(
            "review authentication security changes", role_override="review", effort_override="low", explicit=True
        )
        self.assertEqual(
            (p.decision.role, p.agent, p.requested_effort, p.applied_effort), ("review", "reasoning", "low", "high")
        )

    def test_max_becomes_ultra_for_a_lane_whose_picker_has_no_max(self):
        no_max = ["low", "medium", "high", "xhigh", "ultra"]
        cfg = {"models": {"codex": {"execution": {"primary": "gpt-6.1-terra", "efforts": no_max}}}}
        p = route("add a button", role_override="implementation", effort_override="max", explicit=True, repo_config=cfg)
        self.assertEqual((p.model, p.requested_effort, p.applied_effort), ("gpt-6.1-terra", "max", "ultra"))
        p = route(
            "add a button", role_override="implementation", effort_override="xhigh", explicit=True, repo_config=cfg
        )
        self.assertEqual(p.applied_effort, "xhigh")

    def test_max_stays_max_when_the_lane_lists_max(self):
        cfg = {"models": {"codex": {"execution": {"primary": "gpt-6.1-terra", "efforts": ["high", "max", "ultra"]}}}}
        p = route("add a button", role_override="implementation", effort_override="max", explicit=True, repo_config=cfg)
        self.assertEqual(p.applied_effort, "max")

    def test_classifier_exhaustion_raises_instead_of_defaulting(self):
        with self.assertRaisesRegex(RuntimeError, "all classifiers failed"):
            route(
                "Fix parser.py",
                registry=registry(FakeBackend(error=RuntimeError())),
                repo_config={"difficulty": {"backend": "fake"}},
            )

    def test_every_non_blank_prompt_reaches_a_backend_without_target(self):
        for text in ("What is the capital of France?", "재실행해야해?"):
            backend = FakeBackend("fix")
            plan = route(text, registry=registry(backend), repo_config={"difficulty": {"backend": "fake"}})
            self.assertEqual((plan.target, backend.calls), (ROUTE, 1))
        backend = FakeBackend("fix")
        plan = route("  ", registry=registry(backend), repo_config={"difficulty": {"backend": "fake"}})
        self.assertEqual((plan.target, backend.calls), (NO_ROUTE, 0))

    def test_repo_summary_is_propagated_to_the_classifier_input(self):
        backend = FakeBackend(target="route", provides_target=True)
        route(
            "현재 진행 상황 파악",
            registry=registry(backend),
            repo_config={"difficulty": {"backend": "fake"}},
            repo_summary="model-effort-router-next",
        )
        self.assertEqual(backend.last_task.repo_summary, "model-effort-router-next")


KOREAN = "원인 파악해"
CFG = {"difficulty": {"backend": "first", "fallback": "second"}}


class TargetFromBackendTest(unittest.TestCase):
    def plan(self, message, first, second=None):
        reg = {"first": lambda: first, "second": lambda: second or FakeBackend(name="second")}
        return route(message, registry=reg, repo_config=CFG)

    def test_backend_target_route_uses_its_decision(self):
        first, second = (
            FakeBackend("fix", target="route", name="first", provides_target=True),
            FakeBackend(name="second"),
        )
        p = self.plan(KOREAN, first, second)
        self.assertEqual((p.target, p.decision.role, p.decision.backend, second.calls), (ROUTE, "fix", "first", 0))

    def test_backend_no_route_keeps_decision_without_model_mapping(self):
        p = self.plan("fix parser.py", FakeBackend(target="no_route", name="first", provides_target=True))
        self.assertEqual((p.target, p.decision.target, p.model, p.applied_effort), (NO_ROUTE, "no_route", None, None))

    def test_failed_target_backend_falls_back_to_the_next_backend_for_any_prompt(self):
        for text in (KOREAN, "Fix parser.py"):
            first, second = (
                FakeBackend(error=RuntimeError(), name="first", provides_target=True),
                FakeBackend(name="second"),
            )
            p = self.plan(text, first, second)
            self.assertEqual((p.target, p.decision.backend, second.calls), (ROUTE, "second", 1))

    def test_failed_target_backend_is_not_asked_twice(self):
        first = FakeBackend(error=RuntimeError(), name="first", provides_target=True)
        with self.assertRaisesRegex(RuntimeError, "all classifiers failed"):
            route(
                "Fix parser.py",
                registry={"first": lambda: first, "second": lambda: FakeBackend(error=RuntimeError(), name="second")},
                repo_config=CFG,
            )
        self.assertEqual(first.calls, 1)

    def test_explicit_bypasses_backend_target(self):
        first = FakeBackend(target="no_route", name="first", provides_target=True)
        p = route(
            KOREAN,
            registry={"first": lambda: first},
            repo_config={"difficulty": {"backend": "first", "fallback": "none"}},
            explicit=True,
        )
        self.assertEqual((p.target, p.decision.backend), (ROUTE, "first"))

    def test_target_backend_failure_without_fallback_is_an_error_for_any_prompt(self):
        cfg = {"difficulty": {"backend": "first", "fallback": "none"}}
        reg = {"first": lambda: FakeBackend(error=RuntimeError(), name="first", provides_target=True)}
        for text in (KOREAN, "Fix parser.py"):
            with self.assertRaisesRegex(RuntimeError, "all classifiers failed"):
                route(text, registry=reg, repo_config=cfg)

    def test_target_answers_from_fallback_slot_backends_are_ignored(self):
        first = FakeBackend(error=RuntimeError(), name="first")
        second = FakeBackend("fix", target="no_route", name="second", provides_target=True)
        for text in ("Fix parser.py", KOREAN):
            p = self.plan(text, first, second)
            self.assertEqual((p.target, p.decision.backend), (ROUTE, "second"))

    def test_fallback_list_is_tried_in_order_and_each_failure_is_recorded(self):
        first = FakeBackend(error=RuntimeError(), name="first", provides_target=True)
        second = FakeBackend(error=RuntimeError(), name="second")
        third = FakeBackend("fix", name="third")
        reg = {"first": lambda: first, "second": lambda: second, "third": lambda: third}
        cfg = {"difficulty": {"backend": "first", "fallback": ["second", "third"]}}
        p = route(KOREAN, registry=reg, repo_config=cfg)
        self.assertEqual(
            (p.target, p.decision.backend, first.calls, second.calls, third.calls), (ROUTE, "third", 1, 1, 1)
        )
        self.assertEqual(p.classifier_causes, ("first:RuntimeError", "second:RuntimeError"))

    def test_fallback_list_validation(self):
        reg = {"first": lambda: FakeBackend(name="first")}
        for bad in ([], [1], ["first", None], 5):
            with self.assertRaisesRegex(ValueError, "difficulty.fallback"):
                route("fix x", registry=reg, repo_config={"difficulty": {"backend": "first", "fallback": bad}})
        with self.assertRaisesRegex(ValueError, "unknown difficulty.fallback: 'nope'"):
            route(
                "fix x", registry=reg, repo_config={"difficulty": {"backend": "first", "fallback": ["first", "nope"]}}
            )

    def test_target_backend_answer_without_a_target_routes(self):
        p = self.plan(KOREAN, FakeBackend(name="first", provides_target=True))
        self.assertEqual((p.target, p.decision.backend), (ROUTE, "first"))

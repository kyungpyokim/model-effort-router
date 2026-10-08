import json
import unittest

from model_effort_router.difficulty.decision import DifficultyDecision, DifficultyInput
from model_effort_router.difficulty.subscription import SubscriptionBackend
from model_effort_router.logging import route_log
from model_effort_router.policy.router import RoutePlan, route
from model_effort_router.policy.targeting import NO_ROUTE

STREAM = "\n".join(
    [
        json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": '{"role":"implementation","effort":"medium"}'},
            }
        ),
        json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 29757,
                    "cached_input_tokens": 6912,
                    "cache_write_input_tokens": 0,
                    "output_tokens": 20,
                    "reasoning_output_tokens": 0,
                },
            }
        ),
    ]
)


class NoRouteEventTest(unittest.TestCase):
    def test_no_route_plan_with_decision_logs_target_and_classifier_effort(self):
        plan = RoutePlan(NO_ROUTE, "auto", DifficultyDecision("analysis", "low", "jev", target="no_route"))
        ev = route_log.route_event(plan, latency_ms=1, prompt="p", configured_backend="jev")
        self.assertEqual(ev["target"], "no_route")
        self.assertEqual(
            (ev["decision"]["target"], ev["decision"]["effort"], ev["decision"]["requested_effort"]),
            ("no_route", "low", "low"),
        )

    def test_decision_without_target_has_no_target_key(self):
        plan = route("x", role_override="fix", effort_override="low", explicit=True)
        self.assertNotIn(
            "target", route_log.route_event(plan, latency_ms=1, prompt="p", configured_backend="a")["decision"]
        )


class ClassifierUsageInRouteTest(unittest.TestCase):
    class B:
        def __init__(self, name, usage, exc=None, calls_model=True):
            self.name, self.last_usage, self.exc, self.calls_model = name, usage, exc, calls_model

        def classify(self, task, timeout_s):
            if self.exc:
                raise self.exc
            return DifficultyDecision("implementation", "medium", self.name)

    def route(self, *backends):
        registry = {b.name: (lambda b=b: b) for b in backends}
        cfg = {
            "difficulty": {"backend": backends[0].name, "fallback": backends[1].name if len(backends) > 1 else "none"}
        }
        return route("Fix the bug in parser.py", repo_config=cfg, registry=registry)

    def test_usage_summed_across_primary_and_fallback_including_failed_primary(self):
        u1 = {"input_tokens": 10, "output_tokens": 1, "junk": "x"}
        u2 = {"input_tokens": 5, "cached_input_tokens": 2, "output_tokens": 3}
        plan = self.route(self.B("a", u1, RuntimeError("bad")), self.B("b", u2))
        self.assertEqual(
            plan.classifier_usage,
            {"input_tokens": 15, "cached_input_tokens": 2, "output_tokens": 4, "reasoning_output_tokens": 0},
        )
        ev = route_log.route_event(plan, latency_ms=1, prompt="p", configured_backend="a")
        self.assertEqual(ev["classifier_usage"], plan.classifier_usage)

    def test_model_backend_without_usage_is_missing_and_logged_as_explicit_null(self):
        plan = self.route(self.B("a", None))
        self.assertTrue(plan.classifier_usage_missing)
        ev = route_log.route_event(plan, latency_ms=1, prompt="p", configured_backend="a")
        self.assertIn("classifier_usage", ev)
        self.assertIsNone(ev["classifier_usage"])

    def test_rule_only_backend_means_no_key_at_all(self):
        plan = self.route(self.B("a", None, calls_model=False))
        self.assertFalse(plan.classifier_usage_missing)
        self.assertIsNone(plan.classifier_usage)
        ev = route_log.route_event(plan, latency_ms=1, prompt="p", configured_backend="a")
        self.assertNotIn("classifier_usage", ev)

    def test_fallback_that_never_ran_is_not_missing(self):
        plan = self.route(self.B("a", {"input_tokens": 3}), self.B("b", None))
        self.assertFalse(plan.classifier_usage_missing)
        self.assertEqual(plan.classifier_usage["input_tokens"], 3)

    def test_partial_usage_from_two_model_backends_is_missing(self):
        plan = self.route(self.B("a", {"input_tokens": 3}, RuntimeError("x")), self.B("b", None))
        self.assertTrue(plan.classifier_usage_missing)


class ClassifierUsageTest(unittest.TestCase):
    def test_subscription_backend_exposes_last_usage(self):
        backend = SubscriptionBackend(runner=lambda *a, **k: STREAM)
        self.assertIsNone(backend.last_usage)
        backend.classify(DifficultyInput("x"), 5)
        self.assertEqual(backend.last_usage["input_tokens"], 29757)

    def test_last_usage_reset_at_start_of_each_call(self):
        calls = iter([STREAM, "boom"])

        def runner(*a, **k):
            out = next(calls)
            if out == "boom":
                raise RuntimeError("classifier failed")
            return out

        backend = SubscriptionBackend(runner=runner)
        backend.classify(DifficultyInput("x"), 5)
        self.assertIsNotNone(backend.last_usage)
        with self.assertRaises(RuntimeError):
            backend.classify(DifficultyInput("x"), 5)
        self.assertIsNone(backend.last_usage)  # no stale usage from the previous call

    def test_subscription_backend_is_marked_as_calling_a_model(self):
        self.assertTrue(SubscriptionBackend.calls_model)

    def test_missing_usage_is_none_not_error(self):
        backend = SubscriptionBackend(runner=lambda *a, **k: STREAM.splitlines()[0])
        backend.classify(DifficultyInput("x"), 5)
        self.assertIsNone(backend.last_usage)


if __name__ == "__main__":
    unittest.main()

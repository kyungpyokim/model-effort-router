import unittest
from model_effort_router.difficulty.chain import ClassificationError, classify_with_fallback
from model_effort_router.difficulty.decision import DifficultyDecision
from model_effort_router.difficulty.registry import create, register


class Backend:
    def __init__(self, name, result=None, error=None):
        self.name, self.result, self.error = name, result, error

    def classify(self, task, timeout_s):
        if self.error:
            raise self.error
        return self.result


class FallbackChainTest(unittest.TestCase):
    def test_primary_success(self):
        result = DifficultyDecision("fix", "low", "first")
        actual, causes = classify_with_fallback(None, [Backend("first", result)], 2)
        self.assertEqual((actual, causes), (result, ()))

    def test_failure_uses_secondary_provider_and_preserves_cause(self):
        result = DifficultyDecision("analysis", "high", "second")
        actual, causes = classify_with_fallback(
            None, [Backend("first", error=TimeoutError()), Backend("second", result)], 2
        )
        self.assertEqual((actual.backend, causes), ("second", ("first:TimeoutError",)))

    def test_invalid_primary_result_falls_through_to_valid_secondary(self):
        result = DifficultyDecision("analysis", "high", "second")
        actual, causes = classify_with_fallback(None, [Backend("first", {"role": "fix"}), Backend("second", result)], 2)
        self.assertEqual((actual, causes), (result, ("first:InvalidResult",)))

    def test_all_fail_is_error_and_does_not_invent_default_role(self):
        with self.assertRaisesRegex(ClassificationError, "all classifiers failed"):
            classify_with_fallback(None, [Backend("first", error=ValueError())], 2)

    def test_registry_provider_swap_and_removed_composite_migration(self):
        custom = {}
        register("custom", lambda: Backend("custom", DifficultyDecision("test", "medium", "custom")), custom)
        self.assertEqual(create("custom", custom).classify(None, 1).role, "test")
        with self.assertRaisesRegex(ValueError, "nimble_jev.*removed"):
            create("nimble_jev")

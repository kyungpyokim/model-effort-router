import unittest

from model_effort_router.difficulty.chain import classify_with_fallback
from model_effort_router.difficulty.decision import DifficultyDecision, DifficultyInput
from model_effort_router.difficulty.registry import BACKENDS, create, register


class Fake:
    def __init__(self, name, result=None, exc=None):
        self.name, self.result, self.exc, self.calls = name, result, exc, []

    def classify(self, task, timeout_s):
        self.calls.append((task, timeout_s))
        if self.exc:
            raise self.exc
        return self.result


TASK = DifficultyInput(task="do something")


def ok(level, backend):
    return DifficultyDecision(level=level, backend=backend)


class FallbackChainTest(unittest.TestCase):
    def test_fallback_result_carries_the_primary_failure_causes(self):
        d = classify_with_fallback(TASK, [Fake("p", exc=TimeoutError()), Fake("f", ok("L2", "f"))], timeout_s=7)
        self.assertEqual((d.backend, d.reason_codes), ("f", ("fallback_cause:p:TimeoutError",)))
        self.assertEqual(classify_with_fallback(TASK, [Fake("p", ok("L2", "p"))], 7).reason_codes, ())

    def test_primary_success(self):
        p = Fake("p", ok("L2", "p"))
        f = Fake("f", ok("L4", "f"))
        d = classify_with_fallback(TASK, [p, f], timeout_s=7)
        self.assertEqual((d.level, d.backend), ("L2", "p"))
        self.assertEqual(p.calls, [(TASK, 7)])
        self.assertEqual(f.calls, [])

    def test_timeout_falls_to_fallback(self):
        p = Fake("p", exc=TimeoutError())
        f = Fake("f", ok("L4", "f"))
        self.assertEqual(classify_with_fallback(TASK, [p, f], 1).backend, "f")

    def test_invalid_result_falls_to_fallback(self):
        p = Fake("p", result={"level": "L3"})  # not a DifficultyDecision
        f = Fake("f", ok("L1", "f"))
        self.assertEqual(classify_with_fallback(TASK, [p, f], 1).backend, "f")

    def test_exception_falls_to_fallback(self):
        p = Fake("p", exc=ValueError("bad output"))
        f = Fake("f", ok("L5", "f"))
        self.assertEqual(classify_with_fallback(TASK, [p, f], 1).level, "L5")

    def test_all_fail_gives_default_l3(self):
        p = Fake("p", exc=TimeoutError())
        f = Fake("f", exc=RuntimeError("boom"))
        d = classify_with_fallback(TASK, [p, f], 1)
        self.assertEqual((d.level, d.backend), ("L3", "default"))
        self.assertEqual(d.reason_codes, ("p:TimeoutError", "f:RuntimeError"))

    def test_invalid_result_cause_recorded(self):
        d = classify_with_fallback(TASK, [Fake("p", result="nope")], 1)
        self.assertEqual(d.reason_codes, ("p:InvalidResult",))

    def test_no_backends_gives_default(self):
        d = classify_with_fallback(TASK, [], 1)
        self.assertEqual((d.level, d.backend), ("L3", "default"))


class RegistryTest(unittest.TestCase):
    def test_register_and_create(self):
        reg = {}
        register("fake", lambda: Fake("fake"), registry=reg)
        self.assertEqual(create("fake", registry=reg).name, "fake")

    def test_unknown_backend(self):
        with self.assertRaises(KeyError):
            create("nope", registry={})

    def test_duplicate_registration_rejected(self):
        reg = {}
        register("a", lambda: None, registry=reg)
        with self.assertRaises(ValueError):
            register("a", lambda: None, registry=reg)

    def test_default_registry_has_subscription(self):
        self.assertIn("subscription", BACKENDS)
        self.assertEqual(create("subscription").name, "subscription")


if __name__ == "__main__":
    unittest.main()

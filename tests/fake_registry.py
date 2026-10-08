"""Test-only backend registry hook (loaded via MER_TEST_REGISTRY_MODULE, never shipped)."""

import json

from model_effort_router.difficulty.decision import DifficultyDecision


class FakeBackend:
    name = "fake"
    inputs = []  # in-process tests: every DifficultyInput classify() received

    def __init__(self, spec):
        self.spec = spec
        self.last_usage = None
        self.calls_model = bool(spec.get("calls_model", "usage" in spec))
        self.provides_target = "target" in spec

    def classify(self, task, timeout_s):
        FakeBackend.inputs.append(task)
        self.last_usage = self.spec.get("usage")
        if self.spec.get("raise"):
            raise RuntimeError("fake backend failure")
        return DifficultyDecision(
            self.spec.get("role", "implementation"),
            self.spec.get("effort", "medium"),
            "fake",
            confidence=self.spec.get("confidence"),
            target=self.spec.get("target"),
            reason_code=f"timeout_{timeout_s:g}",
        )


def register(registry, env):
    spec = json.loads(env.get("MER_TEST_FAKE_BACKEND") or "{}")
    registry["fake"] = lambda: FakeBackend(spec)

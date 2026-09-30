"""Test-only backend registry hook (loaded via MER_TEST_REGISTRY_MODULE, never shipped)."""
import json

from model_effort_router.difficulty.decision import DifficultyDecision


class FakeBackend:
    name = "fake"

    def __init__(self, spec):
        self.spec = spec

    def classify(self, task, timeout_s):
        if self.spec.get("raise"):
            raise RuntimeError("fake backend failure")
        return DifficultyDecision(
            self.spec.get("level", "L3"), "fake", confidence=self.spec.get("confidence"),
            risk_flags=tuple(self.spec.get("risk_flags", ())), reason_codes=(f"timeout_{timeout_s:g}",))


def register(registry, env):
    spec = json.loads(env.get("MER_TEST_FAKE_BACKEND") or "{}")
    registry["fake"] = lambda: FakeBackend(spec)

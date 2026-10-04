from typing import Protocol

from .decision import DifficultyDecision, DifficultyInput


class DifficultyBackend(Protocol):
    name: str

    def classify(self, task: DifficultyInput, timeout_s: float) -> DifficultyDecision: ...

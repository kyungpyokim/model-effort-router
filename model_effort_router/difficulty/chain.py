"""Classifier fallback chain. Exhaustion is an error; never guess an execution role."""

from .decision import DifficultyDecision


class ClassificationError(RuntimeError):
    pass


def classify_with_fallback(task, backends, timeout_s):
    causes = []
    for backend in backends:
        name = getattr(backend, "name", "?")
        try:
            result = backend.classify(task, timeout_s)
            if isinstance(result, DifficultyDecision):
                return result, tuple(causes)
            causes.append(f"{name}:InvalidResult")
        except Exception as exc:
            causes.append(f"{name}:{type(exc).__name__}")
    raise ClassificationError("all classifiers failed: " + (", ".join(causes) or "no classifier configured"))

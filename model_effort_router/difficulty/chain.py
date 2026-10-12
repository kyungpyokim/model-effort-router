"""Classifier fallback chain. Exhaustion is an error; never guess an execution role."""

from .decision import DifficultyDecision


class ClassificationError(RuntimeError):
    def __init__(self, message, causes=()):
        super().__init__(message)
        self.causes = tuple(causes)  # "name:Type" or "name:HTTP 503"; never exception messages


class HttpStatusError(RuntimeError):
    """A non-2xx classifier response with optional safe provider diagnostics."""

    def __init__(self, name, status, diagnostics=""):
        super().__init__(f"{name} HTTP {status}")
        self.status = status
        self.diagnostics = diagnostics


def _cause(name, exc):
    if isinstance(exc, HttpStatusError):
        cause = f"{name}:HTTP {exc.status}"
        return f"{cause} [{exc.diagnostics}]" if exc.diagnostics else cause
    return f"{name}:{type(exc).__name__}"


def classify_with_fallback(task, backends, timeout_s, prior=()):
    """`prior`: causes of backends that already failed before this call; they lead the returned/raised causes."""
    causes = list(prior)
    for backend in backends:
        name = getattr(backend, "name", "?")
        try:
            result = backend.classify(task, timeout_s)
            if isinstance(result, DifficultyDecision):
                return result, tuple(causes)
            causes.append(f"{name}:InvalidResult")
        except Exception as exc:
            causes.append(_cause(name, exc))
    raise ClassificationError("all classifiers failed: " + (", ".join(causes) or "no classifier configured"), causes)

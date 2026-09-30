"""Fallback chain: primary -> fallback -> default L3 (spec 9)."""
from .decision import DifficultyDecision


def default_decision(causes=()) -> DifficultyDecision:
    return DifficultyDecision(
        level="L3", backend="default", reason_codes=tuple(causes) or ("no_backend",)
    )


def classify_with_fallback(task, backends, timeout_s) -> DifficultyDecision:
    causes = []
    for backend in backends:
        name = getattr(backend, "name", "?")
        try:
            result = backend.classify(task, timeout_s)
        except Exception as exc:  # timeout, bad output, crash: all mean "try the next one"
            causes.append(f"{name}:{type(exc).__name__}")
            continue
        if isinstance(result, DifficultyDecision):
            return result
        causes.append(f"{name}:InvalidResult")
    return default_decision(causes)

"""nimble_jev: ask the local Nimble first and the external Jev only when the answer is not trustworthy (plan 8.3).

Both stages use the "guide" level question. Jev is called when Nimble failed, or its RAW level distribution is
uncertain, or it predicts a plan-only/review-only request, or any risk flag is present (its own or the rule detector's).
Otherwise Nimble's decision is final and the task text never leaves the machine. A selected Jev call that fails raises,
so the fallback chain moves on: the Nimble answer is never silently used for a case it was not trusted for.
Validated on the 300 new cases of corpus-v3 (270 level-scored; synthetic, AI-labeled): 260/270 exact, critical miss 1/127, Jev on ~71% of cases.
"""
import time
from dataclasses import replace

from .decision import DifficultyDecision, DifficultyInput
from .jev import GUIDE_LEVEL_QUESTION, JevBackend
from .nimble import NimbleBackend
from .risk import detect_risk_flags

UNCERTAIN_TOP = 0.60  # raw top probability below this -> Jev
UNCERTAIN_MARGIN = 0.15  # raw top minus second below this -> Jev
SCOPED_TARGETS = ("plan_only", "review_only")
JEV_RESERVE_S = 2.0  # Nimble never uses the last 2 s: a selected Jev call keeps a usable budget
MIN_JEV_BUDGET_S = 1.0
USAGE_KEYS = ("input_tokens", "output_tokens")


def select_reasons(decision, task):
    """Why Jev should look at a Nimble decision, in a fixed order; () = keep Nimble's answer."""
    probs = sorted((decision.distribution or {}).values(), reverse=True)
    uncertain = len(probs) < 2 or probs[0] < UNCERTAIN_TOP or probs[0] - probs[1] < UNCERTAIN_MARGIN
    return tuple(name for name, selected in (
        ("uncertain", uncertain),
        ("scoped", decision.target in SCOPED_TARGETS),
        ("risk", bool(decision.risk_flags or detect_risk_flags(task.task, task.paths))),
    ) if selected)


def _sum_usage(*usages):
    got = [u for u in usages if isinstance(u, dict)]
    return {k: sum(u.get(k, 0) for u in got) for k in USAGE_KEYS} if got else None


class NimbleJevBackend:
    name = "nimble_jev"
    calls_model = True  # route events log the summed usage of both stages
    provides_target = True

    def __init__(self, nimble=None, jev=None, options=None, env=None, clock=time.monotonic):
        self._nimble = nimble or NimbleBackend(env=env, options=options, level_question=GUIDE_LEVEL_QUESTION)
        self._jev = jev or JevBackend(env=env, level_question=GUIDE_LEVEL_QUESTION)
        self._clock = clock
        self.last_usage = None  # both stages' usage summed (None if neither reported)
        self.last_risk_scores = None  # raw scores of the stage whose decision is returned

    def classify(self, task: DifficultyInput, timeout_s: float) -> DifficultyDecision:
        self.last_usage = self.last_risk_scores = None
        deadline = self._clock() + timeout_s
        decision, reasons, failure = None, (), None
        try:
            decision = self._nimble.classify(task, max(timeout_s - JEV_RESERVE_S, MIN_JEV_BUDGET_S))
            reasons = select_reasons(decision, task)
        except Exception as exc:  # timeout, connection refused, bad answer: Jev gets the case
            reasons, failure = ("nimble_failure",), type(exc).__name__
        nimble_usage = getattr(self._nimble, "last_usage", None)  # reported even when the answer was unusable
        if not reasons:
            self.last_usage, self.last_risk_scores = _sum_usage(nimble_usage), getattr(self._nimble, "last_risk_scores", None)
            return replace(decision, backend=self.name, reason_codes=decision.reason_codes + ("nimble_jev:nimble",))
        try:
            jev_decision = self._jev.classify(task, max(deadline - self._clock(), MIN_JEV_BUDGET_S))
        except Exception as exc:
            self.last_usage = _sum_usage(nimble_usage, getattr(self._jev, "last_usage", None))
            raise RuntimeError(f"nimble_jev: jev failed ({type(exc).__name__}) after {'+'.join(reasons)}"
                               + (f"; nimble failed ({failure})" if failure else "")) from exc
        self.last_usage = _sum_usage(nimble_usage, getattr(self._jev, "last_usage", None))
        self.last_risk_scores = getattr(self._jev, "last_risk_scores", None)
        return replace(jev_decision, backend=self.name, reason_codes=jev_decision.reason_codes
                       + ("nimble_jev:jev",) + tuple(f"nimble_jev_why:{r}" for r in reasons))

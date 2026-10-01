"""Session profile and escalation ladder (spec 11.4): one profile per request, escalated on failure."""
from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

from ..difficulty.decision import RISK_FLAGS
from ..profiles.profiles import Profile
from .stages import _risk_floors

E, B, F = "economy", "balanced", "frontier"

# level -> (start, ladder of at most two escalation steps; running out = stop and report, plan_first)
# plan_first for L3 was dropped after the pilot (extra tokens); risk floors with a plan minimum still force it
SESSION_TABLE = {
    "L1": (Profile(E, "medium"), (Profile(E, "high"), Profile(B, "high")), False),
    "L2": (Profile(E, "medium"), (Profile(B, "high"), Profile(F, "high")), False),
    "L3": (Profile(B, "high"), (Profile(F, "high"), Profile(F, "xhigh")), False),
    "L4": (Profile(F, "high"), (Profile(F, "xhigh"),), True),
    "L5": (Profile(F, "xhigh"), (), True),
}
REVIEW_BY_LEVEL = {"L4": Profile(F, "high"), "L5": Profile(F, "xhigh")}
REVIEW_DEFAULT = Profile(F, "high")  # explicit review_only requests


@dataclass(frozen=True)
class SessionPlan:
    level: Optional[str]  # None: manual mode, nothing was classified
    start: Profile
    ladder: Tuple[Profile, ...]
    plan_first: bool
    review: Optional[Profile]
    plan_profile: Profile  # used by plan_only requests
    applied_rules: Tuple[str, ...]

    def to_dict(self) -> dict:
        prof = lambda p: {"tier": p.tier, "effort": p.effort} if p else None
        return {"level": self.level, "start": prof(self.start), "ladder": [prof(p) for p in self.ladder],
                "plan_first": self.plan_first, "review": prof(self.review), "applied_rules": list(self.applied_rules)}


def _dominates(p: Profile, base: Profile) -> bool:
    return p != base and p.at_least(base) == p


def session_plan(decision, risk_flags=(), overrides: Optional[Mapping] = None) -> SessionPlan:
    """`decision` None = manual mode (needs a session override). `overrides`: {"session": Profile}."""
    session = (overrides or {}).get("session")
    if decision is None and session is None:
        raise ValueError("session_plan needs a decision or a session override")
    flags = set(risk_flags) | set(decision.risk_flags if decision else ())
    flags = tuple(f for f in RISK_FLAGS if f in flags)
    floors = _risk_floors(flags)
    rules = ["level_default"] if decision else []
    rules += [f"risk_min:{f}" for f in flags]

    level = decision.level if decision else None
    start, rungs, plan_first = SESSION_TABLE[level] if level else (None, (), False)
    plan_first = plan_first or "plan" in floors
    # Independent review only for L4/L5 (pilot v2: on flagged L1-L3 work it duplicated the session's own reviews
    # and doubled usage); a risk flag still raises that review's profile to its floor.
    review = REVIEW_BY_LEVEL.get(level)
    if review and "review" in floors:
        review = review.at_least(floors["review"])

    # Risk never moves the session profile (default or override): its minimums are plan-first and the
    # floor of the L4/L5 independent review (spec 11.4), which an override cannot remove.
    if session:
        rules.append("override:session")
        start = session
        rungs = tuple(p for p in rungs if _dominates(p, start))
    plan_profile = Profile(F, "xhigh" if level == "L5" else "high").at_least(floors.get("plan", REVIEW_DEFAULT))
    return SessionPlan(level, start, tuple(rungs), plan_first, review, plan_profile, tuple(rules))

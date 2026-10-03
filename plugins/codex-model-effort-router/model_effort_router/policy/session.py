"""Session profile and escalation ladder (spec 11.4): one profile per request, escalated on failure."""
from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

from ..difficulty.decision import RISK_FLAGS
from ..profiles.profiles import Profile

E, B, F = "economy", "balanced", "frontier"

# 11.2 -- risk minimums. A "plan" minimum forces plan-first; a "review" minimum is the floor of the independent
# review (which only L4/L5 and REVIEW_FLAGS get, spec 11.4).
RISK_MINIMUMS = {
    "security": {"plan": Profile(F, "high"), "review": Profile(F, "high")},
    "auth": {"plan": Profile(F, "high"), "review": Profile(F, "high")},
    "payment": {"plan": Profile(F, "high"), "review": Profile(F, "high")},
    "data_migration": {"plan": Profile(F, "high"), "review": Profile(F, "xhigh")},
    "data_loss": {"plan": Profile(F, "high"), "review": Profile(F, "xhigh")},
    "concurrency": {"review": Profile(F, "high")},
}
assert set(RISK_MINIMUMS) == set(RISK_FLAGS)

# level -> (start, ladder of at most two escalation steps; running out = stop and report, plan_first)
# plan_first for L3 was dropped after the pilot (extra tokens); risk floors with a plan minimum still force it
SESSION_TABLE = {
    "L1": (Profile(E, "medium"), (Profile(E, "high"), Profile(B, "high")), False),
    "L2": (Profile(E, "medium"), (Profile(B, "high"), Profile(F, "high")), False),
    "L3": (Profile(B, "high"), (Profile(F, "high"), Profile(F, "xhigh")), False),
    "L4": (Profile(F, "high"), (Profile(F, "xhigh"),), True),
    "L5": (Profile(F, "xhigh"), (), True),
}
# Codex subagents (`-c agents.*`) per phase: 0 = disabled, n = enabled with n concurrent threads, None = Codex default.
# The user's global AGENTS.md makes sessions spawn 1-5 subagents, the biggest remaining cost lever.
IMPLEMENT_SUBAGENTS = {"L1": 0, "L2": 0, "L3": 0, "L4": 0, "L5": 1}
REVIEW_SUBAGENTS = 0
REVIEW_BY_LEVEL = {"L4": Profile(F, "high"), "L5": Profile(F, "xhigh")}
REVIEW_DEFAULT = Profile(F, "high")  # explicit review_only requests; auth/security work below L4
REVIEW_FLAGS = ("auth", "security")  # these still get an independent review below L4 (a misjudged level must not drop it)
# With the implement session's subagents off, nothing else checks this work (measurement B, plan 22.3: an L3
# concurrency test that could not fail), so these flags also get the independent review below L4.
REVIEW_FLAGS_WITHOUT_SUBAGENTS = ("concurrency", "data_loss")


@dataclass(frozen=True)
class SessionPlan:
    level: Optional[str]  # None: manual mode, nothing was classified
    start: Profile
    ladder: Tuple[Profile, ...]
    plan_first: bool
    review: Optional[Profile]
    plan_profile: Profile  # used by plan_only requests
    applied_rules: Tuple[str, ...]
    implement_subagents: Optional[int] = None  # implement session and its resumes; None: manual mode / "codex" policy
    review_subagents: Optional[int] = None

    def to_dict(self) -> dict:
        def prof(p):
            return {"tier": p.tier, "effort": p.effort} if p else None
        return {"level": self.level, "start": prof(self.start), "ladder": [prof(p) for p in self.ladder],
                "plan_first": self.plan_first, "review": prof(self.review), "applied_rules": list(self.applied_rules),
                "implement_subagents": self.implement_subagents, "review_subagents": self.review_subagents}


def _risk_floors(risk_flags) -> dict:
    floors = {}
    for flag in (f for f in RISK_FLAGS if f in risk_flags):
        for stage, floor in RISK_MINIMUMS[flag].items():
            floors[stage] = floors[stage].at_least(floor) if stage in floors else floor
    return floors


def _dominates(p: Profile, base: Profile) -> bool:
    return p != base and p.at_least(base) == p


def session_plan(decision, risk_flags=(), overrides: Optional[Mapping] = None, subagent_policy="level") -> SessionPlan:
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
    # Independent review for L4/L5, and below L4 only for auth/security (pilot v2: on other flagged L1-L3 work it
    # duplicated the session's own reviews and doubled usage); a risk flag raises the review to its floor.
    capped = subagent_policy == "level"
    implement_subagents = IMPLEMENT_SUBAGENTS.get(level) if capped else None
    review_flags = REVIEW_FLAGS + (REVIEW_FLAGS_WITHOUT_SUBAGENTS if implement_subagents == 0 else ())
    review = REVIEW_BY_LEVEL.get(level) or (REVIEW_DEFAULT if set(flags) & set(review_flags) else None)
    if review and "review" in floors:
        review = review.at_least(floors["review"])

    # Risk never moves the session profile (default or override): its minimums are plan-first and the
    # floor of the L4/L5 independent review (spec 11.4), which an override cannot remove.
    if session:
        rules.append("override:session")
        start = session
        rungs = tuple(p for p in rungs if _dominates(p, start))
    plan_profile = Profile(F, "xhigh" if level == "L5" else "high").at_least(floors.get("plan", REVIEW_DEFAULT))
    return SessionPlan(level, start, tuple(rungs), plan_first, review, plan_profile, tuple(rules),
                       implement_subagents, REVIEW_SUBAGENTS if capped else None)

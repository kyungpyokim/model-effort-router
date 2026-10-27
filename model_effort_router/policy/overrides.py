"""Strict first-line `/router` controls, including an explicit single-phase role/effort."""

from dataclasses import dataclass

from ..difficulty.decision import EFFORTS, ROLES, TIERS
from .config import MODES

COMMAND = "/router"


@dataclass(frozen=True)
class Override:
    mode: str = None
    role: str = None
    effort: str = None
    tier: str = None
    rejected: bool = False

    @property
    def is_empty(self):
        return self.mode is None and self.role is None and self.effort is None and self.tier is None

    def as_config(self):
        return {"router": {"mode": self.mode}} if self.mode else {}


NO_OVERRIDE = Override()
REJECTED = Override(rejected=True)


def parse_override(message):
    if not isinstance(message, str):
        return NO_OVERRIDE, message
    first, _, rest = message.partition("\n")
    if not first.startswith(COMMAND) or first.split()[:1] != [COMMAND]:
        return NO_OVERRIDE, message
    values = {}
    for token in first.split()[1:]:
        t = "auto" if token == "on" else token
        if t in MODES and "mode" not in values:
            values["mode"] = t
            continue
        key, sep, value = token.partition("=")
        if not sep or key in values:
            return REJECTED, rest
        if key == "mode" and value == "on":
            value = "auto"
        values[key] = value
    if len(values) == 1 and "mode" in values and values["mode"] in MODES:
        return Override(mode=values["mode"]), rest
    if values.keys() in ({"role", "effort"}, {"role", "effort", "tier"}):
        if values["role"] in ROLES and values["effort"] in EFFORTS and values.get("tier", "economy") in TIERS:
            return Override(role=values["role"], effort=values["effort"], tier=values.get("tier")), rest
    return REJECTED, rest

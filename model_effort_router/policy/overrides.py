"""Strict first-line `/router` controls, including an explicit single-phase role/effort."""
from dataclasses import dataclass

from ..difficulty.decision import EFFORTS, ROLES
from .config import MODES

COMMAND = "/router"


@dataclass(frozen=True)
class Override:
    mode: str = None
    role: str = None
    effort: str = None
    rejected: bool = False

    @property
    def is_empty(self):
        return self.mode is None and self.role is None and self.effort is None

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
        if token in MODES and "mode" not in values:
            values["mode"] = token
            continue
        key, sep, value = token.partition("=")
        if not sep or key in values:
            return REJECTED, rest
        values[key] = value
    if len(values) == 1 and "mode" in values and values["mode"] in MODES:
        return Override(mode=values["mode"]), rest
    if set(values) == {"role", "effort"} and values["role"] in ROLES and values["effort"] in EFFORTS:
        return Override(role=values["role"], effort=values["effort"]), rest
    return REJECTED, rest

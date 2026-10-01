"""User-typed override commands (spec 3.6).

Only the message's FIRST line, starting at column 0 with `/router`, is a command.
Quoted (`>`), indented, fenced, later-line or mid-sentence text is never interpreted.
Any invalid token voids the whole command (fail safe: nothing is overridden), is flagged
`rejected`, and the command line is still stripped from the text the Router works on.
"""
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Optional

from ..profiles.profiles import STAGES, Profile, parse_profile
from .config import MODES

COMMAND = "/router"


@dataclass(frozen=True)
class Override:
    mode: str = None
    stages: Mapping[str, Profile] = field(default_factory=lambda: MappingProxyType({}))
    rejected: bool = False
    session: Optional[Profile] = None  # `session=tier:effort`: the request-level profile (spec 11.4)

    @property
    def is_empty(self) -> bool:
        return self.mode is None and not self.stages and self.session is None

    def as_config(self) -> dict:
        return {"router": {"mode": self.mode}} if self.mode else {}


NO_OVERRIDE = Override()
REJECTED = Override(rejected=True)


def _parse_tokens(tokens):
    mode, stages, session = None, {}, None
    for tok in tokens:
        if tok in MODES and mode is None:
            mode = tok
        elif tok.startswith("session="):
            if session is not None:
                return None
            session = parse_profile(tok.partition("=")[2])
        elif "=" in tok:
            stage, _, value = tok.partition("=")
            if stage not in STAGES or stage in stages:
                return None
            stages[stage] = parse_profile(value)
        else:
            return None
    return Override(mode, MappingProxyType(stages), session=session)


def parse_override(message):
    """Return (Override, message_without_command_line)."""
    if not isinstance(message, str):
        return NO_OVERRIDE, message
    first, _, rest = message.partition("\n")
    if not first.startswith(COMMAND) or first.split()[:1] != [COMMAND]:  # column 0, exact word
        return NO_OVERRIDE, message
    tokens = first.split()[1:]
    try:
        parsed = _parse_tokens(tokens) if tokens else None
    except ValueError:
        parsed = None
    return (parsed or REJECTED), rest

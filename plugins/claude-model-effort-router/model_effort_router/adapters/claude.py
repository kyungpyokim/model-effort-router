"""Claude Code host adapter: abstract profile -> model + effort. Same Resolved shape as adapters/codex.py."""
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Mapping, Optional, Tuple

from ..profiles.profiles import EFFORTS, TIERS, Profile
from .codex import EFFORT_ORDER, _apply_support

CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")  # `claude --effort` choices (CLI 2.1.280 --help)
CONTEXTS = ("lean", "full")
HAIKU = "claude-haiku-4-5"  # no supported efforts: the flag is omitted
_FIVE = CLAUDE_EFFORTS
# Per-model supported efforts (plan Phase 5, 2026-10-02 decision). An empty tuple = the model takes no --effort.
_MODEL_EFFORTS = MappingProxyType({"claude-sonnet-5-5": _FIVE, "claude-opus-5-5": _FIVE, HAIKU: ()})
_TIERS = MappingProxyType({"economy": "claude-sonnet-5-5", "balanced": "claude-sonnet-5-5", "frontier": "claude-opus-5-5"})
# xhigh -> high: pilot-c1 (2026-10-03) L5 at Opus xhigh + review cost 3.7x a stock Opus run that also passed;
# an escalation step from high to xhigh is then a plain retry at the same profile
_EFFORTS = MappingProxyType({"medium": "medium", "high": "high", "xhigh": "high"})


@dataclass(frozen=True)
class ClaudeConfig:
    tiers: Mapping[str, str] = field(default_factory=lambda: _TIERS)
    efforts: Mapping[str, str] = field(default_factory=lambda: _EFFORTS)
    model_efforts: Mapping[str, Tuple[str, ...]] = field(default_factory=lambda: _MODEL_EFFORTS)
    context: str = "lean"  # session.claude_context: "lean" drops plugins/user settings/MCP, "full" loads everything (host/claude_exec)
    guards: Optional[Callable[[], dict]] = None  # lean: the user's deny/ask/sandbox settings to pass through (default: read the file)

    def __post_init__(self):
        if self.context not in CONTEXTS:
            raise ValueError(f"context must be one of {CONTEXTS}, got {self.context!r}")
        if set(self.tiers) != set(TIERS):
            raise ValueError(f"tiers must define exactly {TIERS}")
        if set(self.efforts) != set(EFFORTS):
            raise ValueError(f"efforts must define exactly {EFFORTS}")
        for abstract, host in self.efforts.items():
            if host not in CLAUDE_EFFORTS:
                raise ValueError(f"efforts[{abstract!r}]={host!r} is not one of {CLAUDE_EFFORTS}")
        for model, supported in self.model_efforts.items():
            if not isinstance(supported, (tuple, list)):
                raise ValueError(f"model {model!r}: supported efforts must be a list (empty = no --effort)")
            unknown = [e for e in supported if e not in CLAUDE_EFFORTS]
            if unknown:
                raise ValueError(f"model {model!r}: unknown efforts {unknown}")
        for tier, model in self.tiers.items():
            if model not in self.model_efforts:
                raise ValueError(f"tier {tier!r} uses model {model!r} with no supported-effort data")


@dataclass(frozen=True)
class ResolvedProfile:
    tier: str
    model: str
    requested_effort: str  # after the abstract -> host effort map
    applied_effort: Optional[str]  # after the model-support fallback; None = the model takes no effort flag


def resolve(profile: Profile, config: ClaudeConfig = ClaudeConfig()) -> ResolvedProfile:
    model = config.tiers[profile.tier]
    requested = config.efforts[profile.effort]
    supported = config.model_efforts[model]
    applied = _apply_support(requested, supported) if supported else None  # nearest higher supported, else highest
    return ResolvedProfile(profile.tier, model, requested, applied)

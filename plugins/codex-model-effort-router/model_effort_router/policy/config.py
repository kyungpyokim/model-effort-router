"""Config precedence: task override > repo > user global > defaults (spec 3.6).

Takes already-parsed dicts; file loading (JSON/YAML) is left to the host hook layer.
"""
from dataclasses import dataclass
from types import MappingProxyType
from typing import Optional

from ..difficulty.nimble import validate_options as validate_nimble
from ..adapters.claude import CONTEXTS as CLAUDE_CONTEXTS  # lean = CLAUDE.md + guard rails, full = plugins/user settings/MCP too

MODES = ("auto", "manual", "off")
SUBAGENT_POLICIES = ("level", "codex")  # level: per-level Codex subagent caps (spec 11.4); codex: no flags
SECTIONS = ("router", "difficulty", "session")

DEFAULTS = MappingProxyType(
    {
        "router": {"mode": "auto"},
        "difficulty": {"backend": "subscription", "fallback": "none", "timeout_s": 10},
        "session": {"subagent_policy": "level", "claude_context": "lean"},
    }
)


@dataclass(frozen=True)
class RouterConfig:
    mode: str
    backend: str
    fallback: str
    timeout_s: float
    subagent_policy: str = "level"
    claude_context: str = "lean"
    nimble: Optional[dict] = None  # validated `difficulty.nimble` options (None = defaults/env)


def _check_layer(layer, name):
    if layer is None:
        return {}
    if not isinstance(layer, dict):
        raise ValueError(f"{name} config must be a dict, got {type(layer).__name__}")
    for section in SECTIONS:
        if section in layer and not isinstance(layer[section], dict):
            raise ValueError(f"{name} config section {section!r} must be a dict")
    return layer


def resolve_config(task=None, repo=None, user=None, registry=None) -> RouterConfig:
    """`registry` (name -> factory), when given, validates backend/fallback names."""
    merged = {s: dict(DEFAULTS[s]) for s in SECTIONS}
    for name, layer in (("user", user), ("repo", repo), ("task", task)):  # lowest -> highest
        layer = _check_layer(layer, name)
        for section in SECTIONS:
            merged[section].update(layer.get(section, {}))
    router, diff, sess = merged["router"], merged["difficulty"], merged["session"]
    if router["mode"] not in MODES:
        raise ValueError(f"router.mode must be one of {MODES}, got {router['mode']!r}")
    if sess["subagent_policy"] not in SUBAGENT_POLICIES:
        raise ValueError(f"session.subagent_policy must be one of {SUBAGENT_POLICIES}, got {sess['subagent_policy']!r}")
    if sess["claude_context"] not in CLAUDE_CONTEXTS:
        raise ValueError(f"session.claude_context must be one of {CLAUDE_CONTEXTS}, got {sess['claude_context']!r}")
    timeout = diff["timeout_s"]
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("difficulty.timeout_s must be a positive number")
    for key in ("backend", "fallback"):
        if not isinstance(diff[key], str):
            raise ValueError(f"difficulty.{key} must be a string")
    if registry is not None and router["mode"] == "auto":  # off/manual never call a backend
        for key in ("backend", "fallback"):
            if diff[key] != "none" and diff[key] not in registry:
                raise ValueError(f"unknown difficulty.{key}: {diff[key]!r}")
        if diff["backend"] == "none":
            raise ValueError("difficulty.backend cannot be 'none'")
    nimble = validate_nimble(diff["nimble"]) if "nimble" in diff else None
    return RouterConfig(router["mode"], diff["backend"], diff["fallback"], timeout, sess["subagent_policy"],
                        sess["claude_context"], nimble)

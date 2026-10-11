"""Router configuration: repo values override user values, then built-in defaults."""

import re
from dataclasses import dataclass
from math import isfinite
from types import MappingProxyType
from typing import Optional

from ..difficulty.decision import EFFORTS
from ..difficulty.laya import validate_options as validate_laya
from ..difficulty.nimble import validate_options as validate_nimble

MODES = ("auto", "manual", "off", "policy")  # "policy": experimental, no classifier (Main picks the lane)
MIN_CONTEXT_CHARS, MAX_CONTEXT_CHARS = 500, 20000
SECTIONS = ("router", "difficulty", "models", "context", "jev", "openai")
PASSTHROUGH_SECTIONS = ("gate",)  # owned by the independent mer-gate CLI
DEFAULTS = {
    "router": {"mode": "auto"},
    "difficulty": {"backend": "subscription", "fallback": "none", "timeout_s": 10},
    "context": {"enabled": True, "max_chars": 6000},
    "models": {
        "codex": {
            "execution": {
                "primary": "gpt-6-luna",
                "fallback": "gpt-6.1-sol",
                "efforts": list(EFFORTS),
            },
            "reasoning": {
                "primary": "gpt-6.1-sol",
                "alternatives": ["gpt-6-astra"],
                "fallback": "gpt-6-luna",
                "efforts": list(EFFORTS),
            },
        },
        "claude": {
            "execution": {
                "primary": "claude-sonnet-5-5",
                "fallback": "claude-opus-5-5",
                "efforts": list(EFFORTS),
            },
            "reasoning": {
                "primary": "claude-opus-5-5",
                "alternatives": ["claude-fable-5-1"],
                "fallback": "claude-sonnet-5-5",
                "efforts": list(EFFORTS),
            },
        },
        "antigravity": {
            "execution": {
                "primary": "gemini-3.8-flash",
                "fallback": None,
                "efforts": ["medium", "high"],
            },
            "reasoning": {
                "primary": "claude-opus-5-5",
                "fallback": None,
                "efforts": ["medium", "high"],
            },
        },
        "opencode": {
            "execution": {
                "primary": "opencode/mimo-v2.6-flash-free",
                "fallback": None,
                "efforts": list(EFFORTS),
            },
            "reasoning": {
                "primary": "opencode/nemotron-3-ultra-free",
                "alternatives": [
                    "opencode-go/glm-5.3",
                    "opencode-go/kimi-k3",
                    "opencode-go/grok-4.7",
                ],
                "fallback": None,
                "efforts": list(EFFORTS),
            },
        },
    },
}


@dataclass(frozen=True)
class RouterConfig:
    mode: str
    backend: str
    fallback: object  # a backend name, or a list of names tried in order
    timeout_s: float
    models: object
    nimble: Optional[dict] = None
    context_enabled: bool = True
    context_max_chars: int = 6000
    laya: Optional[dict] = None

    @property
    def chain(self):
        """Classifier backends in the order they are tried; "none" slots are dropped."""
        fallback = [self.fallback] if isinstance(self.fallback, str) else list(self.fallback)
        return tuple(name for name in (self.backend, *fallback) if name != "none")


def _layer(value, name):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{name} config must be an object")
    unknown = set(value) - set(SECTIONS) - set(PASSTHROUGH_SECTIONS)
    if unknown:
        legacy = "; remove legacy session/profile settings and use role + effort" if "session" in unknown else ""
        raise ValueError(f"{name} config has unknown sections: {sorted(unknown)}{legacy}")
    for section in value:
        if not isinstance(value[section], dict):
            raise ValueError(f"{name} config section {section!r} must be an object")
    return value


def _validate_models(raw):
    for host, groups in raw.items():
        if host not in ("codex", "claude", "antigravity", "opencode") or not isinstance(groups, dict):
            raise ValueError(f"models.{host} must be a host mapping")
        if set(groups) != {"execution", "reasoning"}:
            raise ValueError(f"models.{host} must define execution and reasoning")
        for lane, item in groups.items():
            if not isinstance(item, dict) or set(item) - {
                "primary",
                "fallback",
                "alternatives",
                "efforts",
            }:
                raise ValueError(f"models.{host}.{lane} has unknown or invalid settings")
            for key in ("primary", "fallback"):
                model = item.get(key)
                if model is None and key == "fallback":
                    continue
                if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", model):
                    raise ValueError(f"models.{host}.{lane}.{key} must be a valid model slug (1-128 ASCII characters)")
            alternatives = item.get("alternatives", [])
            if not isinstance(alternatives, list) or any(
                not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", model)
                for model in alternatives
            ):
                raise ValueError(f"models.{host}.{lane}.alternatives must be a list of valid model slugs")
            if len(set(alternatives)) != len(alternatives) or item.get("primary") in alternatives:
                raise ValueError(f"models.{host}.{lane}.alternatives must be unique and exclude primary")
            efforts = item.get("efforts")
            if not isinstance(efforts, list) or not efforts or any(e not in EFFORTS for e in efforts):
                raise ValueError(f"models.{host}.{lane}.efforts must list supported efforts")
    return raw


def resolve_config(task=None, repo=None, user=None, registry=None) -> RouterConfig:
    merged = {
        key: (
            {h: {k: dict(v) for k, v in groups.items()} for h, groups in value.items()}
            if key == "models"
            else {name: dict(item) if isinstance(item, dict) else item for name, item in value.items()}
        )
        for key, value in DEFAULTS.items()
    }
    for name, source in (("user", user), ("repo", repo), ("task", task)):
        source = _layer(source, name)
        for section in ("jev", "openai"):
            if section in source:
                if name != "user":
                    raise ValueError(f"{section} credentials are only allowed in global user config")
                credentials = source[section]
                allowed = {"api_key", "model"} if section == "jev" else {"api_key"}
                model = credentials.get("model")
                if (
                    set(credentials) - allowed
                    or not isinstance(credentials.get("api_key", ""), str)
                    or ("model" in credentials and not (isinstance(model, str) and model))
                ):
                    raise ValueError(
                        f"user {section} config accepts only a string api_key (and, for jev, a non-empty string model)"
                    )
        for key in SECTIONS:
            if key in ("jev", "openai"):
                continue
            if key == "models":
                for host, groups in source.get(key, {}).items():
                    merged[key].setdefault(host, {})
                    for lane, options in groups.items():
                        current = merged[key][host].setdefault(lane, {})
                        if "primary" in options and "alternatives" not in options:
                            alternatives = current.get("alternatives", [])
                            if isinstance(alternatives, list):
                                current["alternatives"] = [
                                    model for model in alternatives if model != options["primary"]
                                ]
                        current.update(options)
            else:
                merged[key].update(source.get(key, {}))
    router, difficulty = merged["router"], merged["difficulty"]
    if set(router) - {"mode"}:
        raise ValueError(f"unknown router settings: {sorted(set(router) - {'mode'})}")
    if router.get("mode") not in MODES:
        raise ValueError(f"router.mode must be one of {MODES}, got {router.get('mode')!r}")
    if set(difficulty) - {"backend", "fallback", "timeout_s", "nimble", "laya"}:
        raise ValueError("legacy or unknown difficulty settings; remove level thresholds and nimble_jev policy")
    if not isinstance(difficulty.get("backend"), str):
        raise ValueError("difficulty.backend must be a string")
    fallback = difficulty.get("fallback")
    names = [fallback] if isinstance(fallback, str) else fallback
    if not isinstance(names, list) or not names or not all(isinstance(n, str) for n in names):
        raise ValueError("difficulty.fallback must be a string or a non-empty list of strings")
    timeout = difficulty.get("timeout_s")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not isfinite(timeout) or timeout <= 0:
        raise ValueError("difficulty.timeout_s must be a positive finite number")
    if "nimble_jev" in (difficulty["backend"], *names):
        raise ValueError("difficulty backend 'nimble_jev' was removed; use 'nimble' with fallback 'jev'")
    if registry is not None and router["mode"] == "auto":
        for key, name in (("backend", difficulty["backend"]), *(("fallback", n) for n in names)):
            if name != "none" and name not in registry:
                raise ValueError(f"unknown difficulty.{key}: {name!r}")
        if difficulty["backend"] == "none":
            raise ValueError("difficulty.backend cannot be 'none'")
    context = merged["context"]
    if set(context) - {"enabled", "max_chars"}:
        raise ValueError(f"unknown context settings: {sorted(set(context) - {'enabled', 'max_chars'})}")
    if not isinstance(context["enabled"], bool):
        raise ValueError("context.enabled must be true or false")
    limit = context["max_chars"]
    if isinstance(limit, bool) or not isinstance(limit, int) or not MIN_CONTEXT_CHARS <= limit <= MAX_CONTEXT_CHARS:
        raise ValueError(f"context.max_chars must be an integer in [{MIN_CONTEXT_CHARS}, {MAX_CONTEXT_CHARS}]")
    models = MappingProxyType(
        {
            h: MappingProxyType({lane: MappingProxyType(dict(v)) for lane, v in groups.items()})
            for h, groups in merged["models"].items()
        }
    )
    _validate_models(merged["models"])
    nimble = validate_nimble(difficulty["nimble"]) if "nimble" in difficulty else None
    laya = validate_laya(difficulty["laya"]) if "laya" in difficulty else None
    return RouterConfig(
        router["mode"],
        difficulty["backend"],
        difficulty["fallback"],
        float(timeout),
        models,
        nimble,
        context["enabled"],
        limit,
        laya=laya,
    )

"""Router configuration: repo values override user values, then built-in defaults."""

import re
from dataclasses import dataclass
from math import isfinite
from types import MappingProxyType
from typing import Optional

from ..difficulty.decision import EFFORTS
from ..difficulty.nimble import validate_options as validate_nimble

MODES = ("auto", "manual", "off")
SECTIONS = ("router", "difficulty", "models", "jev", "openai")
PASSTHROUGH_SECTIONS = ("gate",)  # owned by the independent mer-gate CLI
DEFAULTS = {
    "router": {"mode": "auto"},
    "difficulty": {"backend": "subscription", "fallback": "none", "timeout_s": 10},
    "models": {
        "codex": {
            "execution": {
                "primary": "gpt-6-luna",
                "fallback": "gpt-6.1-sol",
                "efforts": list(EFFORTS),
            },
            "reasoning": {
                "primary": "gpt-6.1-sol",
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
    fallback: str
    timeout_s: float
    models: object
    nimble: Optional[dict] = None


def _layer(value, name):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{name} config must be an object")
    unknown = set(value) - set(SECTIONS) - set(PASSTHROUGH_SECTIONS)
    if unknown:
        legacy = (
            "; remove legacy session/profile settings and use role + effort"
            if "session" in unknown
            else ""
        )
        raise ValueError(
            f"{name} config has unknown sections: {sorted(unknown)}{legacy}"
        )
    for section in value:
        if not isinstance(value[section], dict):
            raise ValueError(f"{name} config section {section!r} must be an object")
    return value


def _validate_models(raw):
    for host, groups in raw.items():
        if host not in ("codex", "claude", "antigravity", "opencode") or not isinstance(
            groups, dict
        ):
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
                raise ValueError(
                    f"models.{host}.{lane} has unknown or invalid settings"
                )
            for key in ("primary", "fallback"):
                model = item.get(key)
                if model is None and key == "fallback":
                    continue
                if not isinstance(model, str) or not re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", model
                ):
                    raise ValueError(
                        f"models.{host}.{lane}.{key} must be a valid model slug (1-128 ASCII characters)"
                    )
            alternatives = item.get("alternatives", [])
            if not isinstance(alternatives, list) or any(
                not isinstance(model, str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", model)
                for model in alternatives
            ):
                raise ValueError(
                    f"models.{host}.{lane}.alternatives must be a list of valid model slugs"
                )
            if len(set(alternatives)) != len(alternatives) or item.get(
                "primary"
            ) in alternatives:
                raise ValueError(
                    f"models.{host}.{lane}.alternatives must be unique and exclude primary"
                )
            efforts = item.get("efforts")
            if (
                not isinstance(efforts, list)
                or not efforts
                or any(e not in EFFORTS for e in efforts)
            ):
                raise ValueError(
                    f"models.{host}.{lane}.efforts must list supported efforts"
                )
    return raw


def resolve_config(task=None, repo=None, user=None, registry=None) -> RouterConfig:
    merged = {
        key: (
            {h: {k: dict(v) for k, v in groups.items()} for h, groups in value.items()}
            if key == "models"
            else {
                name: dict(item) if isinstance(item, dict) else item
                for name, item in value.items()
            }
        )
        for key, value in DEFAULTS.items()
    }
    for name, source in (("user", user), ("repo", repo), ("task", task)):
        source = _layer(source, name)
        for section in ("jev", "openai"):
            if section in source:
                if name != "user":
                    raise ValueError(
                        f"{section} credentials are only allowed in global user config"
                    )
                credentials = source[section]
                if set(credentials) - {"api_key"} or (
                    "api_key" in credentials
                    and not isinstance(credentials["api_key"], str)
                ):
                    raise ValueError(
                        f"user {section} config only accepts a string api_key"
                    )
        for key in SECTIONS:
            if key in ("jev", "openai"):
                continue
            if key == "models":
                for host, groups in source.get(key, {}).items():
                    merged[key].setdefault(host, {})
                    for lane, options in groups.items():
                        merged[key][host].setdefault(lane, {}).update(options)
            else:
                merged[key].update(source.get(key, {}))
    router, difficulty = merged["router"], merged["difficulty"]
    if set(router) - {"mode"}:
        raise ValueError(f"unknown router settings: {sorted(set(router) - {'mode'})}")
    if router.get("mode") not in MODES:
        raise ValueError(
            f"router.mode must be one of {MODES}, got {router.get('mode')!r}"
        )
    if set(difficulty) - {"backend", "fallback", "timeout_s", "nimble"}:
        raise ValueError(
            "legacy or unknown difficulty settings; remove level thresholds and nimble_jev policy"
        )
    for key in ("backend", "fallback"):
        if not isinstance(difficulty.get(key), str):
            raise ValueError(f"difficulty.{key} must be a string")
    timeout = difficulty.get("timeout_s")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError("difficulty.timeout_s must be a positive finite number")
    if difficulty["backend"] == "nimble_jev" or difficulty["fallback"] == "nimble_jev":
        raise ValueError(
            "difficulty backend 'nimble_jev' was removed; use 'nimble' with fallback 'jev'"
        )
    if registry is not None and router["mode"] == "auto":
        for key in ("backend", "fallback"):
            if difficulty[key] != "none" and difficulty[key] not in registry:
                raise ValueError(f"unknown difficulty.{key}: {difficulty[key]!r}")
        if difficulty["backend"] == "none":
            raise ValueError("difficulty.backend cannot be 'none'")
    models = MappingProxyType(
        {
            h: MappingProxyType(
                {lane: MappingProxyType(dict(v)) for lane, v in groups.items()}
            )
            for h, groups in merged["models"].items()
        }
    )
    _validate_models(merged["models"])
    nimble = validate_nimble(difficulty["nimble"]) if "nimble" in difficulty else None
    return RouterConfig(
        router["mode"],
        difficulty["backend"],
        difficulty["fallback"],
        float(timeout),
        models,
        nimble,
    )

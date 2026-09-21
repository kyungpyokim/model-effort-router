"""Model matrix loading, tier application, and platform model policy."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

from classifier import choose_antigravity_model

from rules import (CODE_CHANGE_TASK_TYPES, EFFORT_ORDER, FACTS, LEVELS, OPTIONAL_FACT_DEFAULTS, TASK_TYPES, raise_effort)

SAFE_ORCHESTRATION_LEVELS = ("L5",)

SAFE_ORCHESTRATION_MINIMUM_DELEGABILITY = 2

MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/\-]*$")  # Codex and Claude ids

AGY_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()/:\-]*$")  # display names like "Gemini 3.1 Pro (High)"

AGENT_NAME_RE = re.compile(r"^[a-z0-9-]+$")

SINGLE_ENTRY_KEYS = (
    {"model", "effort"},
    {"patterns", "fallback"},
    {"candidates"},
    {"model", "effort", "fallback_model"},
)

def model_ok(platform: str, model: object) -> bool:
    return isinstance(model, str) and bool((AGY_MODEL_RE if platform == "antigravity" else MODEL_RE).match(model))

def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def positive_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return parsed

def _valid_candidate(cand: object) -> bool:
    return (
        isinstance(cand, dict)
        and "model" in cand
        and isinstance(cand["model"], str)
        and bool(cand["model"].strip())
        and (set(cand) <= {"model", "effort"})
    )

def _valid_stage(stage: object) -> bool:
    if not isinstance(stage, dict) or "role" not in stage:
        return False
    keys = set(stage)
    if keys == {"role", "model", "effort"}:
        return True
    if keys == {"role", "patterns", "fallback"}:
        return True
    if keys == {"role", "candidates"}:
        return isinstance(stage["candidates"], list) and bool(stage["candidates"]) and all(_valid_candidate(c) for c in stage["candidates"])
    if keys == {"role", "model", "effort", "fallback_model"}:
        return True
    return False

def _valid_matrix_entry(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    keys = set(entry)
    if keys in ({"model", "effort"}, {"patterns", "fallback"}, {"model", "effort", "fallback_model"}):
        return True
    if keys == {"candidates"}:
        return isinstance(entry["candidates"], list) and bool(entry["candidates"]) and all(_valid_candidate(c) for c in entry["candidates"])
    return False

def choose_candidate(candidates: list[dict], available: list[str] | None) -> dict:
    if not candidates:
        raise ValueError("candidates list must not be empty")
    if not available:
        return candidates[0]
    for cand in candidates:
        c_model = cand["model"].strip().lower()
        c_norm = re.sub(r"[-_.]+", "-", c_model)
        c_stripped = re.sub(r"^claude-", "", c_norm)
        for avail in available:
            a_model = avail.strip().lower()
            a_norm = re.sub(r"[-_.]+", "-", a_model)
            a_stripped = re.sub(r"^claude-", "", a_norm)
            if c_norm == a_norm or c_stripped == a_stripped:
                return cand
            if a_stripped in ("opus", "sonnet", "haiku") and c_stripped.startswith(a_stripped):
                return cand
    return candidates[-1]

def load_matrix(config: dict, platform: str) -> dict:
    platform_config = config.get("platforms", {}).get(platform)
    matrix = platform_config.get("matrix") if isinstance(platform_config, dict) else None
    if platform_config is None or platform_config.get("routing") != "task_matrix" or not isinstance(matrix, dict):
        raise ValueError(f"config platforms.{platform} must define routing='task_matrix' with a matrix")
    for task_type in TASK_TYPES:
        row = matrix.get(task_type)
        if not isinstance(row, dict):
            raise ValueError(f"{platform} matrix is missing task_type {task_type}")
        for level in LEVELS:
            entry = row.get(level)
            if not isinstance(entry, dict):
                raise ValueError(f"{platform} matrix is missing {task_type}/{level}")
            if "stages" in entry:
                stages = entry["stages"]
                if not isinstance(stages, list) or not stages or not all(_valid_stage(stage) for stage in stages):
                    raise ValueError(f"invalid stage profile at {platform} matrix {task_type}/{level}")
            elif not _valid_matrix_entry(entry):
                raise ValueError(f"entry at {platform} matrix {task_type}/{level} must define model+effort, candidates, patterns+fallback, or stages")
    return matrix

def resolve_stages(matrix: dict, task_type: str, level: str) -> tuple[list[dict], str]:
    entry = matrix[task_type][level]
    if "stages" in entry:
        return [dict(stage) for stage in entry["stages"]], "two_stage"
    return [dict(entry)], "single"

def materialise_stages(platform: str, raw_stages: list[dict], mode: str, available_models: list[str] | None) -> list[dict]:
    """Normalise matrix entries into {role, model, effort} stages, resolving Antigravity patterns and candidates."""
    stages = []
    for stage in raw_stages:
        stage = dict(stage)
        role = stage.get("role", "executor")
        if "patterns" in stage:
            stages.append({
                "role": role,
                "model": choose_antigravity_model(stage, available_models),
                "effort": None,
            })
        elif "candidates" in stage:
            chosen = choose_candidate(stage["candidates"], available_models)
            stages.append({
                "role": role,
                "model": chosen["model"],
                "effort": chosen.get("effort"),
            })
        elif "fallback_model" in stage:
            candidates = [
                {"model": stage["model"], "effort": stage.get("effort")},
                {"model": stage["fallback_model"], "effort": stage.get("effort")},
            ]
            chosen = choose_candidate(candidates, available_models)
            stages.append({
                "role": role,
                "model": chosen["model"],
                "effort": chosen.get("effort"),
            })
        else:
            stages.append({
                "role": role,
                "model": stage["model"],
                "effort": stage.get("effort"),
            })
    return stages

def is_orchestration_eligible(
    config: dict,
    platform: str,
    level: str,
    mode: str,
    risk_flags: dict[str, bool],
    risk_tier: str,
    delegability: int,
) -> bool:
    """Return whether a route is a future orchestration handoff candidate, never an execution decision."""
    policy = config.get("orchestration", {}).get(platform)
    if not isinstance(policy, dict):
        return False
    eligible_levels = policy.get("eligible_levels")
    minimum_delegability = policy.get("minimum_delegability")
    if (
        not isinstance(policy.get("enabled"), bool)
        or not isinstance(eligible_levels, list)
        or not all(level_name in SAFE_ORCHESTRATION_LEVELS for level_name in eligible_levels)
        or minimum_delegability != SAFE_ORCHESTRATION_MINIMUM_DELEGABILITY
    ):
        return False
    return (
        platform == "codex"
        and risk_tier != "critical"
        and mode == "single"
        and level in eligible_levels
        and delegability >= minimum_delegability
        and not any(risk_flags.values())
    )

def load_tier_profile(config: dict, platform: str, risk_tier: str) -> dict:
    tiers = config.get("tiers")
    profile = tiers.get(risk_tier, {}).get(platform) if isinstance(tiers, dict) else None
    if not isinstance(profile, dict):
        raise ValueError(
            f"config platforms.{platform} is missing the {risk_tier} tier profile "
            "(configs older than schema v5 need a `tiers` block; see config/model-map.json)"
        )
    return profile

def apply_tier(
    platform: str, stages: list[dict], profile: dict | None, available_models: list[str] | None
) -> list[dict]:
    """Raise the planning/judging stage for an elevated or critical route.

    The thinking stage is the planner of a two-stage route, otherwise the only stage;
    the implementer keeps its matrix profile. Codex and Claude Code raise the effort,
    Antigravity (which has no effort setting) swaps in the tier's model."""
    if profile is None:
        return stages
    stage = dict(stages[0])
    if platform == "antigravity":
        stage["model"] = choose_antigravity_model(profile, available_models)
    else:
        stage["effort"] = raise_effort(stage["effort"], profile["effort"])
    return [stage, *stages[1:]]

def load_refinements(config: dict, platform: str) -> list[dict]:
    """The platform's optional implementer refinements, validated."""
    refinements = config.get("platforms", {}).get(platform, {}).get("refinements", [])
    if not isinstance(refinements, list):
        raise ValueError(f"config platforms.{platform}.refinements must be a list")
    for ref in refinements:
        valid = (
            isinstance(ref, dict)
            and isinstance(ref.get("task_types"), list) and set(ref["task_types"]) <= set(CODE_CHANGE_TASK_TYPES)
            and ref.get("level") in LEVELS
            and isinstance(ref.get("when"), dict) and ref["when"] and set(ref["when"]) <= set(FACTS)
            and all(value in FACTS[fact] for fact, value in ref["when"].items())
            and isinstance(ref.get("stage"), dict) and _valid_matrix_entry(ref["stage"])
        )
        if not valid:
            raise ValueError(f"invalid refinement in config platforms.{platform}.refinements")
    return refinements

def apply_refinement(
    config: dict, platform: str, task_type: str, level: str, facts: dict[str, str], raw_stages: list[dict], mode: str,
) -> tuple[list[dict], str | None]:
    """Swap a single-stage implementer for a matching refinement (a fact that picks the rung inside a level)."""
    refinements = load_refinements(config, platform)  # validated on every route, not only single-stage ones
    if mode != "single":
        return raw_stages, None
    for ref in refinements:
        if task_type in ref["task_types"] and level == ref["level"] and all(
            facts.get(fact, OPTIONAL_FACT_DEFAULTS.get(fact, "unknown")) == value for fact, value in ref["when"].items()
        ):
            base, refined = raw_stages[0], ref["stage"]
            if (
                base.get("model") == refined.get("model") and base.get("effort") in EFFORT_ORDER and refined.get("effort") in EFFORT_ORDER
                and EFFORT_ORDER.index(refined["effort"]) < EFFORT_ORDER.index(base["effort"])
            ):
                raise ValueError(f"refinement lowers the {platform} {level} matrix effort; a refinement may only raise the rung")
            label = ", ".join(f"{fact}={value}" for fact, value in ref["when"].items())
            return [{"role": raw_stages[0].get("role", "executor"), **ref["stage"]}], label
    return raw_stages, None

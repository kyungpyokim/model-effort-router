#!/usr/bin/env python3
"""Difficulty-based model and effort router for Codex, Claude Code, and Antigravity."""

from __future__ import annotations

import argparse
import json
import math
import re
import shlex
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

FACTORS = ("scope", "ambiguity", "diagnosis", "design", "risk", "verification")
LEVELS = ("L1", "L2", "L3", "L4", "L5")
LEVEL_NAMES = {"L1": "simple", "L2": "standard", "L3": "complex", "L4": "advanced", "L5": "critical"}
CODEX_CLASSIFIER_MODEL = "gpt-5.6-terra"
CLAUDE_CLASSIFIER_MODEL = "claude-sonnet-5"
ANTIGRAVITY_CLASSIFIER_MODEL = "gemini-3.6-flash-low"
CLASSIFIER_EFFORT = "low"
CLASSIFIER_TIMEOUT_SECONDS = 20.0
DETECT_TIMEOUT_SECONDS = 20.0

CLASSIFIER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["level", "factors", "rationale", "hard_floor"],
    "properties": {
        "level": {"type": "string", "enum": list(LEVELS)},
        "factors": {
            "type": "object",
            "additionalProperties": False,
            "required": list(FACTORS),
            "properties": {factor: {"type": "integer", "minimum": 0, "maximum": 2} for factor in FACTORS},
        },
        "rationale": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "hard_floor": {"type": ["string", "null"], "enum": ["L4", "L5", None]},
    },
}

CLASSIFIER_PROMPT = """Classify this coding task only; do not run commands or modify files.
Score scope, ambiguity, diagnosis, design, risk, and verification from 0 to 2.
Map totals 0-2 to L1, 3-5 to L2, 6-8 to L3, 9-10 to L4, and 11-12 to L5.
Apply floors: L4 for authentication/authorization, public API compatibility,
production incidents, database migrations, payments, security-sensitive code, or
multi-service deployments; L5 for irreversible deletion, cryptographic design,
compliance/legal or financial correctness, broad live incidents, or material harm.
Set hard_floor to L4, L5, or null. Return the requested JSON only. Task:\n"""


@dataclass(frozen=True)
class Classification:
    level: str
    factors: dict[str, int]
    rationale: list[str]
    source: str
    hard_floor: str | None = None


@dataclass(frozen=True)
class RouteResult:
    platform: str
    level: str
    level_name: str
    score: int
    factors: dict[str, int]
    model: str
    effort: str | None
    rationale: list[str]
    source: str
    hard_floor: str | None


def agent_name(level: str) -> str:
    return f"level-{level[1:]}-{LEVEL_NAMES[level]}"


def codex_agent_instructions(level: str) -> str:
    filename = f"{agent_name(level)}.toml"
    here = Path(__file__).resolve()
    for candidate in (here.parent.parent / "agents" / filename, here.parent.parent / "plugins" / "codex-model-effort-router" / "agents" / filename):
        if candidate.exists():
            return tomllib.loads(candidate.read_text(encoding="utf-8"))["developer_instructions"]
    raise FileNotFoundError(f"Codex agent profile not found: {filename}")


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def clamp_score(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 2:
        raise ValueError(f"factor score must be 0, 1, or 2; got {value!r}")
    return value


def positive_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return parsed


def normalise_level(level: str) -> str:
    value = level.upper()
    if value not in LEVELS:
        raise ValueError(f"level must be one of {', '.join(LEVELS)}; got {level!r}")
    return value


def level_for_score(score: int) -> str:
    if score <= 2:
        return "L1"
    if score <= 5:
        return "L2"
    if score <= 8:
        return "L3"
    if score <= 10:
        return "L4"
    return "L5"


def higher_level(a: str, b: str) -> str:
    return a if int(a[1:]) >= int(b[1:]) else b


def fallback_classification(reason: str) -> Classification:
    return Classification(
        level="L3",
        factors={factor: 1 for factor in FACTORS},
        rationale=[f"Semantic preflight unavailable ({reason}); safe fallback L3 applied"],
        source="fallback",
        hard_floor=None,
    )


def validate_classifier_output(payload: object, source: str = "classifier") -> Classification:
    if not isinstance(payload, dict) or set(payload) != {"level", "factors", "rationale", "hard_floor"}:
        raise ValueError("response must contain exactly level, factors, rationale, and hard_floor")
    level = payload["level"]
    factors = payload["factors"]
    rationale = payload["rationale"]
    hard_floor = payload["hard_floor"]
    if not isinstance(level, str):
        raise ValueError("level must be a string")
    level = normalise_level(level)
    if not isinstance(factors, dict) or set(factors) != set(FACTORS):
        raise ValueError("factors must contain exactly the six routing factors")
    validated_factors = {factor: clamp_score(factors[factor]) for factor in FACTORS}
    if not isinstance(rationale, list) or not rationale or any(not isinstance(item, str) or not item for item in rationale):
        raise ValueError("rationale must be a non-empty list of strings")
    minimum_level = level_for_score(sum(validated_factors.values()))
    if higher_level(level, minimum_level) != level:
        raise ValueError("level is lower than its factor scores")
    if hard_floor is not None and hard_floor not in ("L4", "L5"):
        raise ValueError("hard_floor must be L4, L5, or null")
    if hard_floor is not None and higher_level(level, hard_floor) != level:
        raise ValueError("level is lower than hard_floor")
    return Classification(level, validated_factors, rationale, source, hard_floor)


def classify_task(
    task: str,
    platform: str = "codex",
    timeout: float = CLASSIFIER_TIMEOUT_SECONDS,
    command: str | None = None,
) -> Classification:
    """Run the platform-native low-effort semantic preflight, falling back to L3."""
    commands = {"codex": "codex", "claude-code": "claude", "antigravity": "agy"}
    if platform not in commands:
        raise ValueError(f"unknown platform: {platform}")
    executable = command or commands[platform]
    try:
        with tempfile.TemporaryDirectory(prefix="model-effort-router-") as directory:
            schema_path = Path(directory) / "classification-schema.json"
            schema_path.write_text(json.dumps(CLASSIFIER_SCHEMA), encoding="utf-8")
            if platform == "codex":
                launch = [
                    executable,
                    "exec",
                    "--ephemeral",
                    "--ignore-user-config",
                    "--ignore-rules",
                    "--sandbox",
                    "read-only",
                    "--cd",
                    directory,
                    "--skip-git-repo-check",
                    "--output-schema",
                    str(schema_path),
                    "--model",
                    CODEX_CLASSIFIER_MODEL,
                    "--config",
                    f'model_reasoning_effort="{CLASSIFIER_EFFORT}"',
                    CLASSIFIER_PROMPT + task,
                ]
            elif platform == "claude-code":
                launch = [
                    executable,
                    "-p",
                    "--model",
                    CLAUDE_CLASSIFIER_MODEL,
                    "--effort",
                    CLASSIFIER_EFFORT,
                    "--output-format",
                    "json",
                    "--json-schema",
                    json.dumps(CLASSIFIER_SCHEMA),
                    "--safe-mode",
                    "--tools",
                    "",
                    "--permission-mode",
                    "plan",
                    "--no-session-persistence",
                    CLASSIFIER_PROMPT + task,
                ]
            else:
                launch = [
                    executable,
                    "--print",
                    "--model",
                    ANTIGRAVITY_CLASSIFIER_MODEL,
                    "--effort",
                    CLASSIFIER_EFFORT,
                    "--mode",
                    "plan",
                    "--sandbox",
                    "--disable-slash-commands",
                    "--output-format",
                    "json",
                    "--json-schema",
                    json.dumps(CLASSIFIER_SCHEMA),
                    CLASSIFIER_PROMPT + task,
                ]
            proc = subprocess.run(
                launch,
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout,
                cwd=directory,
            )
    except subprocess.TimeoutExpired:
        return fallback_classification(f"timed out after {timeout:g}s")
    except OSError:
        return fallback_classification("process could not start")
    if proc.returncode != 0:
        return fallback_classification("process failed")
    try:
        payload = json.loads(proc.stdout)
        if platform in ("claude-code", "antigravity"):
            if not isinstance(payload, dict):
                raise ValueError("structured output must be an object")
            payload = payload["structured_output"]
        source = "terra" if platform == "codex" else CLAUDE_CLASSIFIER_MODEL if platform == "claude-code" else ANTIGRAVITY_CLASSIFIER_MODEL
        return validate_classifier_output(payload, source)
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return fallback_classification("invalid structured output")


def maximum_classification(explicit_factors: dict[str, int] | None) -> Classification:
    """Build the bypass result for an explicit maximum-level request."""
    factors = {factor: 0 for factor in FACTORS}
    for factor, value in (explicit_factors or {}).items():
        if factor not in FACTORS:
            raise ValueError(f"unknown factor: {factor}")
        factors[factor] = clamp_score(value)
    level = level_for_score(sum(factors.values()))
    return Classification(
        level=level,
        factors=factors,
        rationale=["Semantic preflight skipped because explicit L5 is already maximal"],
        source="manual",
        hard_floor=None,
    )


def apply_factor_overrides(classification: Classification, explicit_factors: dict[str, int]) -> Classification:
    factors = dict(classification.factors)
    for factor, value in explicit_factors.items():
        if factor not in FACTORS:
            raise ValueError(f"unknown factor: {factor}")
        factors[factor] = clamp_score(value)
    minimum_level = level_for_score(sum(factors.values()))
    return Classification(
        higher_level(classification.level, minimum_level),
        factors,
        [*classification.rationale, "explicit factor scores applied"],
        classification.source,
        classification.hard_floor,
    )


def read_available_models(command: str = "agy", timeout: float = DETECT_TIMEOUT_SECONDS) -> list[str]:
    try:
        proc = subprocess.run([command, "models"], text=True, capture_output=True, check=False, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"`{command} models` timed out after {timeout:g}s") from exc
    except OSError as exc:
        raise RuntimeError(f"`{command}` could not be executed: {exc}") from exc
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"{command} models failed")
    return [line for raw in proc.stdout.splitlines() if (line := raw.strip().lstrip("-*• ").strip()) and not line.lower().startswith(("available", "models"))]


def choose_antigravity_model(profile: dict, available: list[str] | None) -> str:
    if available:
        for pattern in profile.get("patterns", []):
            for model in available:
                if re.search(pattern, model, re.IGNORECASE):
                    return model
    return profile["fallback"]


def route(
    task: str,
    platform: str,
    config: dict,
    explicit_factors: dict[str, int] | None = None,
    explicit_level: str | None = None,
    available_models: list[str] | None = None,
    classifier: Callable[[str], Classification] | None = None,
) -> RouteResult:
    # An L5 request is already the maximum safe route. Lower explicit levels are
    # minima, so they still need the semantic preflight to discover L4/L5 work.
    manual = explicit_level is not None and normalise_level(explicit_level) == "L5"
    if manual:
        classification = maximum_classification(explicit_factors)
    else:
        classification = classifier(task) if classifier else classify_task(task, platform=platform)
        if explicit_factors:
            classification = apply_factor_overrides(classification, explicit_factors)
    level = higher_level(classification.level, normalise_level(explicit_level)) if explicit_level else classification.level
    rationale = list(classification.rationale)
    if explicit_level:
        rationale.append(f"explicit minimum level {normalise_level(explicit_level)} applied")

    profile = config["platforms"][platform][level]
    if platform == "antigravity":
        model, effort = choose_antigravity_model(profile, available_models), None
    else:
        model, effort = profile["model"], profile["effort"]
    return RouteResult(platform, level, config["levels"][level]["name"], sum(classification.factors.values()), classification.factors, model, effort, rationale, classification.source, classification.hard_floor)


def shell_command(result: RouteResult, task: str, interactive: bool) -> list[str]:
    if result.platform == "codex":
        options = ["-m", result.model, "-c", f"model_reasoning_effort={result.effort}", "-c", f"developer_instructions={json.dumps(codex_agent_instructions(result.level))}"]
        return ["codex", *options, task] if interactive else ["codex", "exec", *options, task]
    if result.platform == "claude-code":
        base = ["claude", "--agent", agent_name(result.level), "--model", result.model, "--effort", str(result.effort)]
        return base + ([task] if interactive else ["-p", task])
    return ["agy", "--agent", agent_name(result.level), "--model", result.model, *( ["--prompt-interactive", task] if interactive else ["--prompt", task] )]


def default_config_path() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here.parent.parent / "config" / "model-map.json", here.parent / "config" / "model-map.json", here.parent.parent.parent / "config" / "model-map.json"):
        if candidate.exists():
            return candidate
    raise FileNotFoundError("config/model-map.json not found")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", help="Task description to classify")
    parser.add_argument("--platform", choices=("codex", "claude-code", "antigravity"), required=True)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--level", choices=(*LEVELS, *(level.lower() for level in LEVELS)))
    for factor in FACTORS:
        parser.add_argument(f"--{factor}", type=int, choices=(0, 1, 2))
    parser.add_argument("--classifier-timeout", type=positive_finite_float, default=CLASSIFIER_TIMEOUT_SECONDS)
    parser.add_argument("--detect-antigravity-models", action="store_true")
    parser.add_argument("--detect-timeout", type=positive_finite_float, default=DETECT_TIMEOUT_SECONDS)
    parser.add_argument("--available-models-file", type=Path)
    parser.add_argument("--format", choices=("json", "text", "command"), default="text")
    parser.add_argument("--interactive", action="store_true", help="Build an interactive-session command")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    config = load_config(args.config or default_config_path())
    explicit_factors = {factor: getattr(args, factor) for factor in FACTORS if getattr(args, factor) is not None}
    available = None
    if args.available_models_file:
        available = [line.strip() for line in args.available_models_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    elif args.detect_antigravity_models:
        try:
            available = read_available_models(timeout=args.detect_timeout)
        except RuntimeError as exc:
            print(f"model detection failed ({exc}); using configured fallbacks", file=sys.stderr)
    result = route(
        args.task,
        args.platform,
        config,
        explicit_factors,
        args.level,
        available,
        classifier=lambda task: classify_task(task, args.platform, args.classifier_timeout),
    )
    if result.source == "fallback":
        print("Semantic preflight failed; safe L3 fallback applied", file=sys.stderr)
    if args.format == "json":
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    elif args.format == "command":
        print(shlex.join(shell_command(result, args.task, args.interactive)))
    else:
        effort = result.effort or "embedded in model"
        print(f"{result.level} ({result.level_name}) | score={result.score} | model={result.model} | effort={effort}")
        print("factors: " + ", ".join(f"{k}={v}" for k, v in result.factors.items()))
        print("reason: " + "; ".join(result.rationale))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

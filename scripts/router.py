#!/usr/bin/env python3
"""Task-type and difficulty based model/effort router for Codex, Claude Code, and Antigravity."""

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
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

FACTORS = ("scope", "ambiguity", "diagnosis", "design", "risk", "verification")
LEVELS = ("L1", "L2", "L3", "L4", "L5")
LEVEL_NAMES = {"L1": "simple", "L2": "standard", "L3": "complex", "L4": "advanced", "L5": "critical"}
TASK_TYPES = ("implementation", "design", "review", "local_refactoring", "architectural_refactoring")
RISK_FLAGS = (
    "security_sensitive",
    "authentication",
    "authorization",
    "payment",
    "data_migration",
    "public_api_change",
)
SECURITY_FLOOR_FLAGS = ("security_sensitive", "authentication", "authorization", "payment")
FALLBACK_TASK_TYPE = "implementation"
SCHEMA_VERSION = 1

CODEX_CLASSIFIER_MODEL = "gpt-5.6-terra"
CLAUDE_CLASSIFIER_MODEL = "claude-sonnet-5"
ANTIGRAVITY_CLASSIFIER_MODEL = "gemini-3.6-flash-low"
CLASSIFIER_EFFORT = "low"
CLASSIFIER_TIMEOUT_SECONDS = 20.0
DETECT_TIMEOUT_SECONDS = 20.0

CLASSIFIER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["task_type", "level", "factors", "risk_flags", "confidence", "reason"],
    "properties": {
        "task_type": {"type": "string", "enum": list(TASK_TYPES)},
        "level": {"type": "string", "enum": list(LEVELS)},
        "factors": {
            "type": "object",
            "additionalProperties": False,
            "required": list(FACTORS),
            "properties": {factor: {"type": "integer", "minimum": 0, "maximum": 2} for factor in FACTORS},
        },
        "risk_flags": {
            "type": "object",
            "additionalProperties": False,
            "required": list(RISK_FLAGS),
            "properties": {flag: {"type": "boolean"} for flag in RISK_FLAGS},
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string", "minLength": 1},
    },
}

CLASSIFIER_PROMPT = """Classify this coding task only; do not run commands or modify files.
Choose exactly one task_type:
- implementation: build or change code directly (features, APIs, UI work, bug fixes, tests).
- design: decide structure or direction without editing code (architecture, API or data-model design, technology choice, implementation planning).
- review: analyse existing code or plans to find problems (code, PR, security, performance, or design review).
- local_refactoring: clean up internals while preserving behaviour and module boundaries (extract functions, renames, deduplication, simplification within one module).
- architectural_refactoring: change module boundaries or system structure AND carry out the resulting edits (module splits, dependency inversion, state-management changes, data-layer redesign, moving responsibilities between services). If only a design is wanted, choose design instead.
Score scope, ambiguity, diagnosis, design, risk, and verification from 0 to 2.
Map totals 0-2 to L1, 3-5 to L2, 6-8 to L3, 9-10 to L4, and 11-12 to L5.
Set each risk_flag true only when the task genuinely involves that area; the router applies a hard L4 floor for security_sensitive/authentication/authorization/payment and one escalation level per data_migration/public_api_change.
Set confidence between 0 and 1. Keep reason to one short sentence. Return the requested JSON only. Task:\n"""

PLANNER_INSTRUCTIONS_TEMPLATE = """You are the planning stage of a two-stage architectural refactoring pipeline.
Analyse the request against the current repository state and produce a structured implementation plan.
Write the plan as JSON to exactly this path: {plan_path}
Use this top-level shape:
{{"schema_version": 1, "analysis": {{"current_structure": [], "constraints": [], "affected_areas": [], "risks": []}}, "implementation_plan": {{"steps": [], "expected_files": [], "compatibility_requirements": []}}, "validation": {{"commands": [], "acceptance_criteria": [], "rollback_notes": []}}}}
Do not modify any repository file. Read-only analysis plus writing the single plan file is allowed.
Cross-check the request against the real repository before writing the plan.
Do not invoke the model-effort router recursively.
If the repository cannot be analysed safely, exit non-zero without writing the plan."""

IMPLEMENTER_INSTRUCTIONS_TEMPLATE = """You are the execution stage of a two-stage architectural refactoring pipeline.
A structured plan file is provided at: {plan_path}
Read the plan together with the original request and the current repository state first.
If the repository conflicts with the plan, stop and report the difference instead of forcing the plan through.
Execute the planned changes, run validation.commands, satisfy acceptance_criteria, and apply rollback_notes when validation fails.
Do not blindly follow the plan when the repository state has moved on from what the planner saw.
Do not invoke the model-effort router recursively."""


@dataclass(frozen=True)
class Classification:
    task_type: str
    level: str
    factors: dict[str, int]
    risk_flags: dict[str, bool]
    confidence: float | None
    reason: str
    source: str


@dataclass(frozen=True)
class RouteResult:
    platform: str
    task_type: str
    base_level: str
    level: str
    level_name: str
    score: int
    factors: dict[str, int]
    risk_flags: dict[str, bool]
    confidence: float | None
    model: str | None
    effort: str | None
    mode: str
    stages: list[dict]
    plan_dir: str | None
    rationale: list[str]
    source: str


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


def normalise_task_type(task_type: str) -> str:
    if task_type not in TASK_TYPES:
        raise ValueError(f"task type must be one of {', '.join(TASK_TYPES)}; got {task_type!r}")
    return task_type


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
    """Safe landing used whenever the semantic preflight cannot produce valid output."""
    return Classification(
        task_type=FALLBACK_TASK_TYPE,
        level="L3",
        factors={factor: 1 for factor in FACTORS},
        risk_flags={flag: False for flag in RISK_FLAGS},
        confidence=None,
        reason=f"Semantic preflight unavailable ({reason}); safe fallback applied",
        source="fallback",
    )


def validate_classifier_output(payload: object, source: str = "classifier") -> Classification:
    required = {"task_type", "level", "factors", "risk_flags", "confidence", "reason"}
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("response must contain exactly task_type, level, factors, risk_flags, confidence, and reason")
    task_type = normalise_task_type(payload["task_type"])
    level = normalise_level(payload["level"])
    factors = payload["factors"]
    risk_flags = payload["risk_flags"]
    confidence = payload["confidence"]
    reason = payload["reason"]
    if not isinstance(factors, dict) or set(factors) != set(FACTORS):
        raise ValueError("factors must contain exactly the six routing factors")
    validated_factors = {factor: clamp_score(factors[factor]) for factor in FACTORS}
    minimum_level = level_for_score(sum(validated_factors.values()))
    if higher_level(level, minimum_level) != level:
        raise ValueError("level is lower than its factor scores")
    if not isinstance(risk_flags, dict) or set(risk_flags) != set(RISK_FLAGS):
        raise ValueError(f"risk_flags must contain exactly {', '.join(RISK_FLAGS)}")
    for flag in RISK_FLAGS:
        if not isinstance(risk_flags[flag], bool):
            raise ValueError(f"risk flag {flag} must be a boolean")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        raise ValueError("confidence must be a number between 0 and 1")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason must be a non-empty string")
    return Classification(task_type, level, validated_factors, dict(risk_flags), float(confidence), reason, source)


def classify_task(
    task: str,
    platform: str = "codex",
    timeout: float = CLASSIFIER_TIMEOUT_SECONDS,
    command: str | None = None,
) -> Classification:
    """Run the platform-native low-effort semantic preflight, falling back to safe defaults."""
    commands = {"codex": "codex", "claude-code": "claude", "antigravity": "agy"}

    def fallback(exc: Exception) -> Classification:
        detail = "timed out" if isinstance(exc, subprocess.TimeoutExpired) else "process could not start" if isinstance(exc, OSError) else "invalid structured output"
        return fallback_classification(detail)

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
                unwrap = lambda raw: json.loads(raw)
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
                unwrap = lambda raw: json.loads(raw)["structured_output"]
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
                unwrap = lambda raw: json.loads(raw)["structured_output"]
            try:
                proc = subprocess.run(
                    launch,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=timeout,
                    cwd=directory,
                )
            except subprocess.TimeoutExpired as exc:
                return fallback(exc)
            except OSError as exc:
                return fallback(exc)
            if proc.returncode != 0:
                return fallback_classification("process failed")
            try:
                payload = unwrap(proc.stdout)
                source = "terra" if platform == "codex" else CLAUDE_CLASSIFIER_MODEL if platform == "claude-code" else ANTIGRAVITY_CLASSIFIER_MODEL
                return validate_classifier_output(payload, source)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                return fallback_classification("invalid structured output")
    except OSError:
        return fallback_classification("temporary directory could not be created")


def apply_risk_escalation(level: str, risk_flags: dict[str, bool]) -> str:
    """Security flags force an L4 floor; other flags escalate one level each."""
    index = LEVELS.index(level)
    index += sum(1 for flag in RISK_FLAGS if flag not in SECURITY_FLOOR_FLAGS and risk_flags.get(flag))
    if any(risk_flags.get(flag) for flag in SECURITY_FLOOR_FLAGS):
        index = max(index, LEVELS.index("L4"))
    return LEVELS[min(index, len(LEVELS) - 1)]


def maximum_classification(explicit_factors: dict[str, int] | None, task_type: str | None) -> Classification:
    """Build the bypass result for an explicit maximum-level request."""
    factors = {factor: 0 for factor in FACTORS}
    for factor, value in (explicit_factors or {}).items():
        if factor not in FACTORS:
            raise ValueError(f"unknown factor: {factor}")
        factors[factor] = clamp_score(value)
    level = level_for_score(sum(factors.values()))
    return Classification(
        task_type=task_type or FALLBACK_TASK_TYPE,
        level=level,
        factors=factors,
        risk_flags={flag: False for flag in RISK_FLAGS},
        confidence=None,
        reason="Semantic preflight skipped because both task_type and maximal level were pinned explicitly",
        source="manual",
    )


def apply_factor_overrides(classification: Classification, explicit_factors: dict[str, int]) -> Classification:
    factors = dict(classification.factors)
    for factor, value in explicit_factors.items():
        if factor not in FACTORS:
            raise ValueError(f"unknown factor: {factor}")
        factors[factor] = clamp_score(value)
    minimum_level = level_for_score(sum(factors.values()))
    return Classification(
        classification.task_type,
        higher_level(classification.level, minimum_level),
        factors,
        classification.risk_flags,
        classification.confidence,
        classification.reason + "; explicit factor scores applied",
        classification.source,
    )


SINGLE_ENTRY_KEYS = ({"model", "effort"}, {"patterns", "fallback"})


def _valid_stage(stage: object) -> bool:
    return isinstance(stage, dict) and (
        set(stage) == {"role", "model", "effort"} or set(stage) == {"role", "patterns", "fallback"}
    )


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
            elif set(entry) not in SINGLE_ENTRY_KEYS:
                raise ValueError(f"entry at {platform} matrix {task_type}/{level} must define model+effort, patterns+fallback, or stages")
    return matrix


def resolve_stages(matrix: dict, task_type: str, level: str) -> tuple[list[dict], str]:
    entry = matrix[task_type][level]
    if "stages" in entry:
        return [dict(stage) for stage in entry["stages"]], "two_stage"
    return [dict(entry)], "single"


def materialise_stages(platform: str, raw_stages: list[dict], mode: str, available_models: list[str] | None) -> list[dict]:
    """Normalise matrix entries into {role, model, effort} stages, resolving Antigravity patterns."""
    stages = []
    for stage in raw_stages:
        stage = dict(stage)
        if "patterns" in stage:
            stage = {
                "role": stage.get("role", "executor"),
                "model": choose_antigravity_model(stage, available_models),
                "effort": None,
            }
        else:
            stage.setdefault("role", "executor")
        stages.append(stage)
    return stages


def route(
    task: str,
    platform: str,
    config: dict,
    explicit_factors: dict[str, int] | None = None,
    explicit_level: str | None = None,
    explicit_task_type: str | None = None,
    available_models: list[str] | None = None,
    classifier: Callable[[str], Classification] | None = None,
) -> RouteResult:
    # The preflight is skipped only when both axes are pinned manually. An
    # explicit L5 alone still classifies so the task_type axis picks the right
    # profile row; the classified level can never lower the explicit maximum.
    manual_bypass = explicit_task_type is not None and explicit_level is not None and normalise_level(explicit_level) == "L5"
    if manual_bypass:
        classification = maximum_classification(explicit_factors, normalise_task_type(explicit_task_type))
    else:
        classification = classifier(task) if classifier else classify_task(task, platform=platform)
        if explicit_factors:
            classification = apply_factor_overrides(classification, explicit_factors)
    task_type = normalise_task_type(explicit_task_type) if explicit_task_type else classification.task_type
    base_level = higher_level(classification.level, normalise_level(explicit_level)) if explicit_level else classification.level
    level = apply_risk_escalation(base_level, classification.risk_flags)

    rationale = [classification.reason]
    if explicit_factors:
        rationale.append("explicit factor scores applied")
    if explicit_level:
        rationale.append(f"explicit minimum level {normalise_level(explicit_level)} applied")
    if explicit_task_type:
        rationale.append(f"explicit task_type {explicit_task_type} applied")

    platform_config = config["platforms"][platform]
    plan_dir = None
    if isinstance(platform_config, dict) and platform_config.get("routing") == "task_matrix":
        matrix = load_matrix(config, platform)
        raw_stages, mode = resolve_stages(matrix, task_type, level)
        stages = materialise_stages(platform, raw_stages, mode, available_models)
        if mode == "two_stage":
            plan_dir = str(Path(tempfile.gettempdir()) / f"codex-route-{uuid.uuid4().hex[:8]}")
            model = effort = None
        else:
            model, effort = stages[0]["model"], stages[0]["effort"]
    elif platform == "antigravity":
        profile = platform_config[level]
        stages, mode = [{"role": "executor", "model": choose_antigravity_model(profile, available_models), "effort": None}], "single"
        model, effort = stages[0]["model"], None
    else:
        profile = platform_config[level]
        stages, mode = [{"role": "executor", "model": profile["model"], "effort": profile["effort"]}], "single"
        model, effort = profile["model"], profile["effort"]

    return RouteResult(
        platform=platform,
        task_type=task_type,
        base_level=base_level,
        level=level,
        level_name=config["levels"][level]["name"],
        score=sum(classification.factors.values()),
        factors=dict(classification.factors),
        risk_flags=dict(classification.risk_flags),
        confidence=classification.confidence,
        model=model,
        effort=effort,
        mode=mode,
        stages=stages,
        plan_dir=plan_dir,
        rationale=rationale,
        source=classification.source,
    )


def shell_command(result: RouteResult, task: str, interactive: bool) -> list[str]:
    """Legacy single-command launcher used by Claude Code and Antigravity platforms."""
    if result.platform == "claude-code":
        base = ["claude", "--agent", agent_name(result.level), "--model", result.model, "--effort", str(result.effort)]
        return base + ([task] if interactive else ["-p", task])
    if result.platform == "antigravity":
        return ["agy", "--agent", agent_name(result.level), "--model", result.model, *( ["--prompt-interactive", task] if interactive else ["--prompt", task] )]
    raise ValueError("use stage_commands for codex results")


PLANNER_PROMPT_PREFIX = "Produce an architectural refactoring plan.\nOriginal request:\n"
IMPLEMENTER_PROMPT_PREFIX = "Execute the prepared refactoring plan.\nOriginal request:\n"


def _codex_exec_command(model: str, effort: str, instructions: str, prompt: str, interactive: bool) -> list[str]:
    options = [
        "-m", model,
        "-c", f"model_reasoning_effort={effort}",
        "-c", f"developer_instructions={json.dumps(instructions)}",
    ]
    return ["codex", *options, prompt] if interactive else ["codex", "exec", *options, prompt]


def _claude_print_command(model: str, effort: str | None, prompt: str) -> list[str]:
    command = ["claude", "-p", "--model", model]
    if effort:
        command += ["--effort", effort]
    return [*command, prompt]


def _agy_prompt_command(model: str, prompt: str) -> list[str]:
    return ["agy", "--model", model, "--prompt", prompt]


def _single_stage_command(result: RouteResult, task: str, interactive: bool) -> list[str]:
    if result.platform == "codex":
        stage = result.stages[0]
        return _codex_exec_command(stage["model"], stage["effort"], codex_agent_instructions(result.level), task, interactive)
    return shell_command(result, task, interactive=False)


def stage_commands(result: RouteResult, task: str, interactive: bool = False) -> list[list[str]]:
    """Build one argv per execution stage. Two-stage runs are always exec/print sessions."""
    if result.mode != "two_stage":
        return [_single_stage_command(result, task, interactive)]
    plan_path = str(Path(result.plan_dir) / "plan.json")
    planner, implementer = result.stages
    instructions = PLANNER_INSTRUCTIONS_TEMPLATE.format(plan_path=plan_path)
    plan_prompt = f"{PLANNER_PROMPT_PREFIX}{task}\n\nWrite the plan JSON to exactly: {plan_path}\n"
    execute_instructions = IMPLEMENTER_INSTRUCTIONS_TEMPLATE.format(plan_path=plan_path)
    execute_prompt = f"{IMPLEMENTER_PROMPT_PREFIX}{task}\n\nPlan file to read first: {plan_path}\n"
    builders = {
        "codex": lambda stage, instr, prompt: _codex_exec_command(stage["model"], stage["effort"], instr, prompt, interactive=False),
        "claude-code": lambda stage, instr, prompt: _claude_print_command(stage["model"], stage["effort"], f"{instr}\n\n{prompt}"),
        "antigravity": lambda stage, instr, prompt: _agy_prompt_command(stage["model"], f"{instr}\n\n{prompt}"),
    }
    build = builders[result.platform]
    return [build(planner, instructions, plan_prompt), build(implementer, execute_instructions, execute_prompt)]


def command_chain(result: RouteResult, task: str, keep_plan: bool = False, interactive: bool = False) -> str | None:
    """Assemble a success-dependent shell chain. Returns None when nothing to print."""
    commands = stage_commands(result, task, interactive)
    parts = [shlex.join(command) for command in commands]
    if result.mode != "two_stage":
        return parts[0]
    prefix = f"mkdir -p {shlex.quote(str(result.plan_dir))}"
    cleanup = "" if keep_plan else f" && rm -rf {shlex.quote(str(result.plan_dir))}"
    return f"{prefix} && {' && '.join(parts)}{cleanup}"


def command_chain_from_payload(payload: object) -> str:
    """Return the already-classified platform command chain from a route JSON payload."""
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("route file must be a current route JSON payload")
    platform = payload.get("platform")
    executable = {"codex": "codex", "claude-code": "claude", "antigravity": "agy"}.get(platform)
    if executable is None:
        raise ValueError("route file must target a supported platform")
    steps = payload.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("route file must contain at least one execution step")
    commands: list[list[str]] = []
    for step in steps:
        command = step.get("command") if isinstance(step, dict) else None
        if not isinstance(command, list) or not command or command[0] != executable or not all(isinstance(arg, str) and arg for arg in command):
            raise ValueError("route file contains an invalid platform command")
        commands.append(command)
    if payload.get("mode") == "single" and len(commands) == 1:
        return shlex.join(commands[0])
    if payload.get("mode") == "two_stage" and len(commands) == 2:
        plan = steps[0].get("output") if isinstance(steps[0], dict) else None
        plan_path = plan.get("path") if isinstance(plan, dict) else None
        if not isinstance(plan_path, str) or not plan_path:
            raise ValueError("two-stage route file must declare its plan output")
        return f"mkdir -p {shlex.quote(str(Path(plan_path).parent))} && {' && '.join(shlex.join(command) for command in commands)}"
    raise ValueError("route file mode does not match its execution steps")


def result_payload(result: RouteResult, commands: list[list[str]] | None = None) -> dict:
    steps: list[dict] = []
    ids = ["plan", "execute"] if result.mode == "two_stage" else ["execute"]
    for position, stage in enumerate(result.stages):
        step = {
            "id": ids[position],
            "role": stage["role"],
            "model": stage["model"],
            "effort": stage["effort"],
            "depends_on": ["plan"] if position == 1 else [],
        }
        if commands:
            step["command"] = commands[position]
        if result.plan_dir:
            plan_file = {"type": "plan_file", "path": str(Path(result.plan_dir) / "plan.json")}
            if position == 0:
                step["output"] = plan_file
            else:
                step["input"] = plan_file
        steps.append(step)
    return {
        "schema_version": SCHEMA_VERSION,
        "platform": result.platform,
        "task_type": result.task_type,
        "base_level": result.base_level,
        "effective_level": result.level,
        "score": result.score,
        "factors": result.factors,
        "risk_flags": [flag for flag, active in result.risk_flags.items() if active],
        "confidence": result.confidence,
        "mode": result.mode,
        "source": result.source,
        "rationale": result.rationale,
        "steps": steps,
    }


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


def default_config_path() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here.parent.parent / "config" / "model-map.json", here.parent / "config" / "model-map.json", here.parent.parent.parent / "config" / "model-map.json"):
        if candidate.exists():
            return candidate
    raise FileNotFoundError("config/model-map.json not found")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", nargs="?", help="Task description to classify")
    parser.add_argument("--route-file", type=Path, help="Replay an already-classified route JSON without classifying again")
    parser.add_argument("--platform", choices=("codex", "claude-code", "antigravity"))
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--level", choices=(*LEVELS, *(level.lower() for level in LEVELS)))
    parser.add_argument(
        "--task-type",
        choices=("auto", *TASK_TYPES),
        default="auto",
        help="Override automatic task-type classification (auto still classifies level and risk)",
    )
    parser.add_argument("--keep-plan", action="store_true", help="Preserve the two-stage plan directory on success")
    for factor in FACTORS:
        parser.add_argument(f"--{factor}", type=int, choices=(0, 1, 2))
    parser.add_argument("--classifier-timeout", type=positive_finite_float, default=CLASSIFIER_TIMEOUT_SECONDS)
    parser.add_argument("--detect-antigravity-models", action="store_true")
    parser.add_argument("--detect-timeout", type=positive_finite_float, default=DETECT_TIMEOUT_SECONDS)
    parser.add_argument("--available-models-file", type=Path)
    parser.add_argument("--format", choices=("json", "text", "command"), default="text")
    parser.add_argument("--interactive", action="store_true", help="Build an interactive-session command (single-stage only)")
    args = parser.parse_args(argv)
    if args.route_file:
        task_options = {
            "--platform", "--config", "--level", "--task-type", "--keep-plan",
            "--classifier-timeout", "--detect-antigravity-models", "--detect-timeout",
            "--available-models-file", "--format", "--interactive",
            *(f"--{factor}" for factor in FACTORS),
        }
        if args.task or any(option in argv for option in task_options):
            parser.error("--route-file cannot be combined with task-routing options")
    elif not args.task or not args.platform:
        parser.error("task and --platform are required unless --route-file is used")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.route_file:
        try:
            payload = json.loads(args.route_file.read_text(encoding="utf-8"))
            print(command_chain_from_payload(payload))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"invalid route file: {exc}", file=sys.stderr)
            return 2
        return 0
    config = load_config(args.config or default_config_path())
    explicit_factors = {factor: getattr(args, factor) for factor in FACTORS if getattr(args, factor) is not None}
    explicit_task_type = None if args.task_type == "auto" else args.task_type
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
        explicit_task_type,
        available,
        classifier=lambda task: classify_task(task, args.platform, args.classifier_timeout),
    )
    if result.source == "fallback":
        print(
            "Semantic preflight failed; safe fallback applied "
            f"({result.task_type} / {result.level})",
            file=sys.stderr,
        )
    if args.format == "json":
        print(json.dumps(result_payload(result, stage_commands(result, args.task)), ensure_ascii=False, indent=2))
    elif args.format == "command":
        chain = command_chain(result, args.task, keep_plan=args.keep_plan, interactive=args.interactive)
        print(chain if chain is not None else shlex.join(shell_command(result, args.task, args.interactive)))
    else:
        stages_text = " -> ".join(f"{stage['role']}={stage['model']}/{stage['effort'] or 'embedded'}" for stage in result.stages)
        active_flags = [flag for flag, active in result.risk_flags.items() if active]
        print(f"{result.level} ({result.level_name}) | type={result.task_type} | mode={result.mode} | score={result.score}")
        print(f"stages: {stages_text}")
        print("factors: " + ", ".join(f"{key}={value}" for key, value in result.factors.items()))
        print("risk flags: " + (", ".join(active_flags) if active_flags else "none"))
        print("reason: " + "; ".join(result.rationale))
        if result.plan_dir:
            print(f"plan dir: {result.plan_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

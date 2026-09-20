#!/usr/bin/env python3
"""Task-type and difficulty based model/effort router for Codex, Claude Code, and Antigravity."""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import re
import shlex
import subprocess
import sys
import tempfile
import tomllib
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

_THIS_MODULE = sys.modules.get(__name__)

import route_reuse  # noqa: E402
from classifier import (  # noqa: E402
    CLASSIFIER_PROMPT,
    CLASSIFIER_SCHEMA,
    CLASSIFIER_TIMEOUT_SECONDS,
    DETECT_TIMEOUT_SECONDS,
    EXIT_NEEDS_ANSWER,
    FACT_QUESTIONS,
    FALLBACK_TASK_TYPE,
    PRIMARY_CLASSIFIER_CONFIG,
    RETRYABLE_FAILURE_KINDS,
    Classification,
    _extract_json_payload,
    apply_answers,
    choose_antigravity_model,
    classifier_prompt,
    classifier_schema_path,
    classify_task,
    classify_task_single,
    fallback_classification,
    merge_lookup,
    pinned_classification,
    read_classification_file,
    settleable,
    validate_classifier_output,
    with_facts,
)
from commands import (  # noqa: E402
    AUTOBAHN_SCOPE_GUARD,
    AUTOBAHN_SCOPE_GUARD_INSTRUCTION,
    CLAUDE_READ_TOOLS,
    CODEX_CONFIG_KEYS,
    IMPLEMENTER_INSTRUCTIONS_TEMPLATE,
    IMPLEMENTER_PROMPT_PREFIX,
    MARKDOWN_AGENT_PLUGINS,
    PLANNER_INSTRUCTIONS_TEMPLATE,
    PLANNER_PROMPT_PREFIX,
    _agy_prompt_command,
    _claude_print_command,
    _codex_exec_command,
    _single_stage_command,
    agent_name,
    claude_access_flags,
    codex_agent_instructions,
    command_chain,
    command_model,
    expected_stage_text,
    handoff_text,
    markdown_agent_instructions,
    replay_command,
    shell_command,
    stage_command,
    stage_commands,
    validate_argv,
    validate_step_instructions,
    validated_commands as _validated_commands,
    verification_handoff_instructions,
    verification_recommendations,
)
from policy import (  # noqa: E402
    AGENT_NAME_RE,
    AGY_MODEL_RE,
    MODEL_RE,
    SAFE_ORCHESTRATION_LEVELS,
    SAFE_ORCHESTRATION_MINIMUM_DELEGABILITY,
    _valid_candidate,
    _valid_matrix_entry,
    _valid_stage,
    apply_refinement,
    apply_tier,
    choose_candidate,
    is_orchestration_eligible,
    load_config,
    load_matrix,
    load_refinements,
    load_tier_profile,
    materialise_stages,
    model_ok,
    positive_finite_float,
    resolve_stages,
)
from rules import (  # noqa: E402
    CODE_CHANGE_TASK_TYPES,
    CRITICAL_SECURITY_DOMAINS,
    DIFFICULTY_RULES,
    EFFORT_ORDER,
    FACTS,
    LEVEL_NAMES,
    LEVELS,
    OPTIONAL_FACT_DEFAULTS,
    READ_ONLY_TASK_TYPES,
    RISK_FLAGS,
    RISK_TIERS,
    SECURITY_DOMAINS,
    SECURITY_FLOOR_FLAGS,
    TASK_TYPES,
    TIER_LEVEL,
    YES_NO,
    YES_NO_UNKNOWN,
    apply_risk_escalation,
    evaluate_rules,
    higher_level,
    higher_tier,
    is_read_only_inspect,
    is_trivial_edit_fast_path,
    normalise_level,
    normalise_task_type,
    normalise_tier,
    raise_effort,
    risk_flags_from_facts,
    unknown_facts,
    unresolved_facts,
)

command_chain_from_payload = replay_command


def validated_commands(payload: object) -> tuple[list[list[str]], str | None]:
    return _validated_commands(payload, router=_THIS_MODULE or sys.modules.get("router"))


SCHEMA_VERSION = 6
SUPPORTED_ROUTE_SCHEMA_VERSIONS = (2, 3, 4, 5, SCHEMA_VERSION)
REVIEW_MIN_LEVEL = "L4"
PIPELINE_LIMITS = {"max_test_fixes": 2, "review_fixes_before_replan": 1, "max_replans": 1}


@dataclass(frozen=True)
class RouteResult:
    platform: str
    task_type: str
    base_level: str
    level: str
    level_name: str
    risk_tier: str
    facts: dict[str, str]
    matched_rules: list[str]
    unresolved: list[str]
    evidence: list[str]
    risk_flags: dict[str, bool]
    model: str | None
    effort: str | None
    mode: str
    stages: list[dict]
    plan_dir: str | None
    rationale: list[str]
    source: str
    execution_strategy: str
    orchestration_eligible: bool
    pipeline: dict | None = None


def claude_agent_delegation(effort: str | None, model: str) -> dict[str, str]:
    alias = re.sub(r"^claude-", "", model).split("-", 1)[0]
    return {"subagent_type": f"model-effort:effort-{effort or 'none'}", "model": alias}


def pipeline_payload(result: RouteResult, task: str | None) -> dict | None:
    if result.pipeline is None:
        return None
    payload = {**result.pipeline, "task": task}
    if result.platform == "claude-code":
        for name in ("review", "replan"):
            stage = payload.get(name)
            if stage:
                payload[name] = {**stage, "agent": claude_agent_delegation(stage.get("effort"), stage["model"])}
    return payload


def result_payload(result: RouteResult, commands: list[list[str]] | None = None, task: str | None = None) -> dict:
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
        if result.platform == "claude-code":
            step["agent"] = claude_agent_delegation(stage.get("effort"), stage["model"])
        if result.plan_dir:
            plan_file = {"type": "plan_file", "path": str(Path(result.plan_dir) / "plan.json")}
            if position == 0:
                step["output"] = plan_file
            else:
                step["input"] = plan_file
        steps.append(step)
    active_risk_flags = [flag for flag, active in result.risk_flags.items() if active]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "platform": result.platform,
        "task_type": result.task_type,
        "base_level": result.base_level,
        "effective_level": result.level,
        "risk_tier": result.risk_tier,
        "facts": result.facts,
        "matched_rules": result.matched_rules,
        "unresolved_facts": result.unresolved,
        "questions": [{"fact": fact, "question": FACT_QUESTIONS[fact], "options": list(FACTS[fact])} for fact in result.unresolved],
        "evidence": result.evidence,
        "risk_flags": active_risk_flags,
        "mode": result.mode,
        "source": result.source,
        "rationale": result.rationale,
        "steps": steps,
        "verification": verification_recommendations(result.task_type, result.level, result.risk_flags, result.mode),
        "execution_strategy": result.execution_strategy,
        "orchestration_eligible": result.orchestration_eligible,
        "pipeline": pipeline_payload(result, task),
    }
    if any(flag in SECURITY_FLOOR_FLAGS for flag in active_risk_flags):
        payload["scope_guard"] = {
            "policy": "autobahn_scope_carve",
            "risk_flags": [flag for flag in active_risk_flags if flag in SECURITY_FLOOR_FLAGS],
            "instruction": AUTOBAHN_SCOPE_GUARD_INSTRUCTION,
        }
    return payload


def pipeline_plan(
    platform: str, task_type: str, level: str, mode: str, matrix: dict, stages: list[dict],
    profile: dict | None, available_models: list[str] | None,
) -> dict | None:
    if task_type not in CODE_CHANGE_TASK_TYPES:
        return None
    review = replan = None
    if LEVELS.index(level) >= LEVELS.index(REVIEW_MIN_LEVEL):
        judge_raw, _ = resolve_stages(matrix, "review", level)
        judge = apply_tier(platform, materialise_stages(platform, judge_raw, "single", available_models), profile, available_models)[0]
        review = {**judge, "role": "reviewer"}
        replan = {**(stages[0] if mode == "two_stage" else judge), "role": "planner"}
    return {"review": review, "replan": replan, "limits": dict(PIPELINE_LIMITS)}


def load_reused_classification(
    session: str, cwd: str, task: str, explicit_task_type: str | None = None,
) -> tuple[Classification | None, dict | None, str]:
    record = route_reuse.load_record(session)
    if record is None:
        return None, None, "no stored route for this session"
    try:
        task_type, level, tier = record["task_type"], record["level"], record["risk_tier"]
        flags, facts, rules = record["risk_flags"], record["facts"], record["matched_rules"]
        if task_type not in TASK_TYPES or level not in LEVELS or tier not in RISK_TIERS:
            raise ValueError("unknown route values")
        if not isinstance(flags, dict) or set(flags) != set(RISK_FLAGS) or not all(isinstance(v, bool) for v in flags.values()):
            raise ValueError("bad risk flags")
        if not isinstance(facts, dict) or not isinstance(rules, list) or not isinstance(record.get("evidence", []), list):
            raise ValueError("bad facts")
        delegability, reuses = record.get("delegability", 0), record.get("reuses", 0)
        if delegability not in (0, 1, 2) or isinstance(reuses, bool) or not isinstance(reuses, int):
            raise ValueError("bad counters")
        if not isinstance(record["saved_at"], (int, float)) or isinstance(record["saved_at"], bool):
            raise ValueError("bad timestamp")
        blockers = route_reuse.reuse_blockers(
            record, cwd, task, task_type in CODE_CHANGE_TASK_TYPES,
            explicit_task_type=normalise_task_type(explicit_task_type) if explicit_task_type else None,
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return None, None, "stored route is invalid"
    if blockers:
        return None, record, "; ".join(blockers)
    classification = Classification(
        task_type=task_type, level=level, risk_flags=dict(flags),
        reason=f"route reused from the session (reuse {reuses + 1}); the classifier was not called",
        source="reused", facts={str(k): str(v) for k, v in facts.items()}, matched_rules=tuple(str(r) for r in rules),
        risk_tier=tier,
        evidence=tuple(str(e) for e in record.get("evidence", [])), delegability=delegability,
    )
    return classification, record, ""


def session_record(result: RouteResult, delegability: int) -> dict:
    return {
        "task_type": result.task_type, "level": result.level, "risk_tier": result.risk_tier,
        "risk_flags": dict(result.risk_flags), "facts": dict(result.facts),
        "matched_rules": list(result.matched_rules), "unresolved": list(result.unresolved),
        "evidence": list(result.evidence), "delegability": delegability,
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
    return [
        (line.split("\t")[-1].strip() if "\t" in line else line)
        for raw in proc.stdout.splitlines()
        if (line := raw.strip().lstrip("-*• ").strip()) and not line.lower().startswith(("available", "models", "fetching"))
    ]


from cli import (  # noqa: E402
    _prompt_axis,
    default_config_path,
    main as _cli_main,
    parse_answer,
    parse_args,
    prompt_manual_classification,
    prompt_unresolved,
)


def main(argv: list[str] | None = None) -> int:
    return _cli_main(argv, router=_THIS_MODULE or sys.modules.get("router"))


def route(
    task: str,
    platform: str,
    config: dict,
    explicit_level: str | None = None,
    explicit_task_type: str | None = None,
    available_models: list[str] | None = None,
    classifier: Callable[[str], Classification] | None = None,
    repo_aware: bool = False,
    critical: bool = False,
) -> RouteResult:
    manual_bypass = explicit_task_type is not None and (critical or explicit_level is not None)
    if manual_bypass:
        classification = pinned_classification(
            normalise_task_type(explicit_task_type), TIER_LEVEL if critical else normalise_level(explicit_level)
        )
    else:
        classification = classifier(task) if classifier else classify_task(
            task, platform=platform, repo_aware=repo_aware, available_models=available_models
        )
    risk_tier = "critical" if critical else classification.risk_tier
    task_type = normalise_task_type(explicit_task_type) if explicit_task_type else classification.task_type

    if explicit_level:
        base_level = higher_level(classification.level, normalise_level(explicit_level))
    else:
        base_level = classification.level

    rationale = [classification.reason]
    if classification.matched_rules:
        rationale.append("rules: " + ", ".join(classification.matched_rules))
    if explicit_level:
        rationale.append(f"explicit minimum level {explicit_level.upper()} applied")
    if explicit_task_type:
        rationale.append(f"explicit task_type {explicit_task_type} applied")

    level, risk_tier = apply_risk_escalation(base_level, risk_tier, classification.risk_flags)
    if risk_tier != "standard":
        rationale.append(f"{risk_tier} risk tier raises the {level} planning/judging effort")

    level_name = config["levels"][level]["name"]
    matrix = load_matrix(config, platform)
    tier_profile = load_tier_profile(config, platform, risk_tier) if risk_tier != "standard" else None
    raw_stages, mode = resolve_stages(matrix, task_type, level)
    raw_stages, refined_by = apply_refinement(config, platform, task_type, level, classification.facts, raw_stages, mode)
    if refined_by:
        rationale.append(f"{level} implementer refined by {refined_by}")

    stages = apply_tier(platform, materialise_stages(platform, raw_stages, mode, available_models), tier_profile, available_models)

    if is_read_only_inspect(task_type, classification.facts):
        execution_strategy = "inspect"
    elif is_trivial_edit_fast_path(task_type, risk_tier, classification.facts):
        execution_strategy = "trivial_edit"
    elif task_type in CODE_CHANGE_TASK_TYPES:
        execution_strategy = "regular"
    else:
        execution_strategy = "direct"

    if execution_strategy == "inspect":
        pipeline = None
    elif execution_strategy == "trivial_edit":
        pipeline = {"review": None, "replan": None, "limits": dict(PIPELINE_LIMITS)}
    else:
        pipeline = pipeline_plan(platform, task_type, level, mode, matrix, stages, tier_profile, available_models)

    plan_dir = None
    if mode == "two_stage":
        plan_dir = str(Path(tempfile.gettempdir()).resolve() / f"codex-route-{uuid.uuid4().hex[:8]}")
        model = effort = None
    else:
        model, effort = stages[0]["model"], stages[0]["effort"]

    orchestration_eligible = is_orchestration_eligible(
        config, platform, level, mode, classification.risk_flags, risk_tier, classification.delegability
    )
    return RouteResult(
        platform=platform,
        task_type=task_type,
        base_level=base_level,
        level=level,
        level_name=level_name,
        risk_tier=risk_tier,
        facts=dict(classification.facts),
        matched_rules=list(classification.matched_rules),
        unresolved=list(classification.unresolved),
        evidence=list(classification.evidence),
        risk_flags=dict(classification.risk_flags),
        model=model,
        effort=effort,
        mode=mode,
        stages=stages,
        plan_dir=plan_dir,
        rationale=rationale,
        source=classification.source,
        execution_strategy="direct",
        orchestration_eligible=orchestration_eligible,
        pipeline=pipeline,
    )


if __name__ == "__main__":
    raise SystemExit(main())

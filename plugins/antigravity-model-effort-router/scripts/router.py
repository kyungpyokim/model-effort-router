#!/usr/bin/env python3

"""Task-type and difficulty based model/effort router for Codex, Claude Code, and Antigravity."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, NoReturn

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

_THIS_MODULE = sys.modules.get(__name__)

import route_reuse

from classifier import (CLASSIFIER_PROMPT, CLASSIFIER_SCHEMA, CLASSIFIER_TIMEOUT_SECONDS, DETECT_TIMEOUT_SECONDS, EXIT_NEEDS_ANSWER, FACT_QUESTIONS, FALLBACK_TASK_TYPE, PRIMARY_CLASSIFIER_CONFIG, RETRYABLE_FAILURE_KINDS, Classification, apply_answers, choose_antigravity_model, classifier_prompt, classify_task, classify_task_single, fallback_classification, merge_lookup, pinned_classification, read_classification_file, settleable, validate_classifier_output, with_facts, _bounded)

from commands import (AGENT_NAME_RE, AUTOBAHN_SCOPE_GUARD, AUTOBAHN_SCOPE_GUARD_INSTRUCTION, CLAUDE_READ_TOOLS, CODEX_CONFIG_KEYS, IMPLEMENTER_INSTRUCTIONS_TEMPLATE, IMPLEMENTER_PROMPT_PREFIX, MARKDOWN_AGENT_PLUGINS, PLANNER_INSTRUCTIONS_TEMPLATE, PLANNER_PROMPT_PREFIX, REVIEW_ROLE_PROMPT, _agy_prompt_command, _claude_print_command, _codex_exec_command, _single_stage_command, agent_name, claude_access_flags, codex_agent_instructions, command_chain, command_model, expected_stage_text, handoff_text, markdown_agent_instructions, role_prompt_prefix, shell_command, stage_command, stage_commands, validate_argv, validate_step_instructions, verification_handoff_instructions, verification_recommendations)
from commands import refuse_interactive_two_stage

from policy import (AGY_MODEL_RE, MODEL_RE, SAFE_ORCHESTRATION_LEVELS, SAFE_ORCHESTRATION_MINIMUM_DELEGABILITY, _valid_candidate, _valid_matrix_entry, _valid_stage, apply_refinement, apply_tier, choose_candidate, is_orchestration_eligible, load_config, load_matrix, load_refinements, load_tier_profile, materialise_stages, model_ok, positive_finite_float, resolve_stages)

from rules import (CODE_CHANGE_TASK_TYPES, CRITICAL_SECURITY_DOMAINS, DIFFICULTY_RULES, EFFORT_ORDER, FACTS, LEVEL_NAMES, LEVELS, NOUL_FACTS, OPTIONAL_FACT_DEFAULTS, READ_ONLY_TASK_TYPES, RISK_FLAGS, RISK_TIERS, SECURITY_DOMAINS, SECURITY_FLOOR_FLAGS, TASK_TYPES, TIER_LEVEL, YES_NO, YES_NO_UNKNOWN, apply_risk_escalation, evaluate_rules, higher_level, higher_tier, normalise_level, normalise_task_type, raise_effort, risk_flags_from_facts, unknown_facts, unresolved_facts)

from cli import (  # noqa: E402
    _prompt_axis, default_config_path, main as _cli_main, parse_answer, parse_args, prompt_manual_classification, prompt_unresolved,
)

SCHEMA_VERSION = 7

SUPPORTED_ROUTE_SCHEMA_VERSIONS = (2, 3, 4, 5, 6, SCHEMA_VERSION)

WORKFLOW_MIN_LEVEL = "L2"

PIPELINE_LIMITS = {"max_test_fixes": 2, "review_fixes_before_replan": 1, "max_replans": 1}
TEST_COMMAND_ENV = "MODEL_EFFORT_ROUTER_TEST_CMD"
ROUTER_PLAN_DIR_RE = re.compile(r"^codex-route-[0-9a-f]{8}$")
ROUTER_PLAN_MARKER = ".model-effort-router-plan"
INSPECT_MAX_LEVEL = "L2"

TRIVIAL_EDIT_TASK_TYPES = ("implementation", "local_refactoring")

TRIVIAL_EDIT_FACTS = {
    "mechanical_only": "yes",
    "files_touched": "1",
    "crosses_module_boundary": "no",
    "crosses_service_boundary": "no",
    "fix_or_result_known": "yes",
    "intermittent_or_concurrency": "no",
    "needs_new_structure": "no",
    "changes_security_or_payment_logic": "no",
    "reviews_security_sensitive_code": "no",
    "security_domain": "none",
    "changes_public_api_contract": "no",
    "changes_persisted_data": "no",
    "irreversible_or_ledger_or_crypto": "no",
    "changes_trust_boundary": "no",
    "blast_radius": "narrow",
    "silent_failure_material_harm": "no",
    "requires_code_understanding": "no",
}


def router_plan_file(path: object) -> Path:
    """Return the one plan artifact path the router is allowed to create or remove."""
    if not isinstance(path, str) or not path:
        raise ValueError("two-stage route file must declare its plan output")
    candidate = Path(os.path.normpath(path))
    if not candidate.is_absolute():
        raise ValueError("route plan path must be absolute")
    temp_dir = Path(tempfile.gettempdir()).resolve()
    marker = candidate.parent / ROUTER_PLAN_MARKER
    if (
        candidate.name != "plan.json"
        or candidate.parent.parent != temp_dir
        or not ROUTER_PLAN_DIR_RE.fullmatch(candidate.parent.name)
        or candidate.parent.is_symlink()
        or candidate.is_symlink()
        or marker.is_symlink()
        or not marker.is_file()
    ):
        raise ValueError("route plan path must be the router-owned codex-route-*/plan.json artifact")
    return candidate

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
    # Who reviews and re-plans after implementation; None for routes without a chained pipeline.
    pipeline: dict | None = None
    # The cheap single-model path this route qualified for ("inspect" / "trivial_edit"), else None.
    fast_path: str | None = None

def claude_agent_delegation(effort: str | None, model: str) -> dict[str, str]:
    """Agent tool arguments for a Claude Code step: the in-session executor keeps the
    session cwd and permissions, which a nested ``claude -p`` does not.

    The Agent tool sets model but not effort, so the subagent is the ``effort-*``
    agent whose frontmatter pins the matrix effort."""
    # Agent tool accepts only family aliases; claude-sonnet-5 -> sonnet.
    alias = re.sub(r"^claude-", "", model).split("-", 1)[0]
    return {"subagent_type": f"model-effort:effort-{effort or 'none'}", "model": alias}

def pipeline_payload(result: RouteResult, task: str | None) -> dict | None:
    if result.pipeline is None:
        return None
    payload = {**result.pipeline, "task": task}
    if result.platform == "claude-code":
        for name in ("review", "replan"):
            stage = payload[name]
            if stage:
                payload[name] = {**stage, "agent": claude_agent_delegation(stage["effort"], stage["model"])}
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
            step["agent"] = claude_agent_delegation(stage["effort"], stage["model"])
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
        "fast_path": result.fast_path,
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
    profile: dict | None, available_models: list[str] | None, fast_path: str | None = None,
) -> dict | None:
    """Who reviews and re-plans a code change once the implementer is done.

    Every code change gets the merged Sol/Opus review and re-plan stage at the risk tier's effort, from the
    ``review`` row of ``max(level, WORKFLOW_MIN_LEVEL)``; only the trivial-edit fast path keeps just the
    deterministic test gate and the cheap fix loop."""
    if task_type not in CODE_CHANGE_TASK_TYPES:
        return None
    if fast_path == "trivial_edit":
        return {"review": None, "replan": None, "limits": dict(PIPELINE_LIMITS)}
    judge_raw, _ = resolve_stages(matrix, "review", higher_level(level, WORKFLOW_MIN_LEVEL))
    judge = apply_tier(platform, materialise_stages(platform, judge_raw, "single", available_models), profile, available_models)[0]
    review = {**judge, "role": "reviewer"}
    # A two-stage route already has its planner; a single-stage one re-plans with the judge.
    replan = {**(stages[0] if mode == "two_stage" else judge), "role": "planner"}
    return {"review": review, "replan": replan, "limits": dict(PIPELINE_LIMITS)}

def load_reused_classification(
    session: str, cwd: str, task: str, explicit_task_type: str | None = None,
) -> tuple[Classification | None, dict | None, str]:
    """The stored session classification when no blocker fires, else ``None`` and why not."""
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
        if any("kill switch" in b for b in blockers):
            route_reuse.invalidate_record(session, "Jev kill switch active")
        return None, record, "; ".join(blockers)
    classification = Classification(
        task_type=task_type, level=level, risk_flags=dict(flags),
        reason=f"route reused from the session (reuse {reuses + 1}); the classifier was not called",
        source="reused", facts={str(k): str(v) for k, v in facts.items()}, matched_rules=tuple(str(r) for r in rules),
        risk_tier=tier, evidence=tuple(_bounded(str(e)) for e in record.get("evidence", [])), delegability=delegability,
    )
    return classification, record, ""

def session_record(result: RouteResult, delegability: int, origin: str | None = None) -> dict:
    return {
        "task_type": result.task_type, "level": result.level, "risk_tier": result.risk_tier,
        "risk_flags": dict(result.risk_flags), "facts": dict(result.facts),
        "matched_rules": list(result.matched_rules), "unresolved": list(result.unresolved),
        "evidence": list(result.evidence), "delegability": delegability,
        "origin": origin if origin is not None else result.source,
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

def fast_path_for(task_type: str, level: str, risk_tier: str, facts: dict[str, str], check_available: bool) -> str | None:
    """The cheap single-model path a route qualifies for, or None for the regular workflow.

    A trivial edit must satisfy every mechanical, local, and low-risk fact. ``unknown`` is never an
    affirmative fact, so it keeps the regular workflow without raising anything."""
    facts = {**OPTIONAL_FACT_DEFAULTS, **facts}
    if task_type == "inspect" and set(facts) == set(FACTS):
        return "inspect"
    if (
        task_type in TRIVIAL_EDIT_TASK_TYPES and level == "L1" and risk_tier == "standard" and check_available
        and all(facts.get(name) == value for name, value in TRIVIAL_EDIT_FACTS.items())
    ):
        return "trivial_edit"
    return None

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
    check_available: bool = False,
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
    # Inspect is an intentionally narrow Luna/Haiku-only lookup. A classifier that calls an investigation or
    # safety judgement "inspect" is inconsistent and must be reclassified, never silently promoted to Sol/Opus.
    if task_type == "inspect" and (risk_tier != "standard" or LEVELS.index(level) > LEVELS.index(INSPECT_MAX_LEVEL)):
        raise ValueError(
            f"inspect must be a standard L1-L2 read-only lookup (got {level} / {risk_tier}); "
            "classify judgement as review or design instead"
        )

    level_name = config["levels"][level]["name"]
    matrix = load_matrix(config, platform)
    tier_profile = load_tier_profile(config, platform, risk_tier) if risk_tier != "standard" else None
    raw_stages, mode = resolve_stages(matrix, task_type, level)
    raw_stages, refined_by = apply_refinement(config, platform, task_type, level, classification.facts, raw_stages, mode)
    if refined_by:
        rationale.append(f"{level} implementer refined by {refined_by}")
    stages = materialise_stages(platform, raw_stages, mode, available_models)
    fast_path = fast_path_for(task_type, level, risk_tier, classification.facts, check_available)
    if mode == "single" and task_type in CODE_CHANGE_TASK_TYPES and fast_path != "trivial_edit":
        # The planning judge is the design row of max(level, L2); the implementer keeps its real-level matrix/refined rung.
        planner_raw, _ = resolve_stages(matrix, "design", higher_level(level, WORKFLOW_MIN_LEVEL))
        planner = materialise_stages(platform, planner_raw, "single", available_models)[0]
        # A planner identical to the implementer buys nothing, so that route stays single-stage.
        if (planner["model"], planner["effort"]) != (stages[0]["model"], stages[0]["effort"]):
            stages = [{**planner, "role": "planner"}, {**stages[0], "role": "implementer"}]
            mode = "two_stage"
    stages = apply_tier(platform, stages, tier_profile, available_models)
    pipeline = pipeline_plan(platform, task_type, level, mode, matrix, stages, tier_profile, available_models, fast_path)
    plan_dir = None
    if mode == "two_stage":
        # Resolved once (macOS /var -> /private/var) so the prompt, the Claude edit rule and the route agree.
        plan_path = Path(tempfile.gettempdir()).resolve() / f"codex-route-{uuid.uuid4().hex[:8]}"
        plan_path.mkdir(mode=0o700)
        (plan_path / ROUTER_PLAN_MARKER).write_text("router-owned\n", encoding="utf-8")
        plan_dir = str(plan_path)
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
        fast_path=fast_path,
    )

def validated_commands(payload: object) -> tuple[list[list[str]], str | None]:
    """Validate a route JSON payload; return its execution-step argvs and the plan file path (two-stage only)."""
    if not isinstance(payload, dict) or payload.get("schema_version") not in SUPPORTED_ROUTE_SCHEMA_VERSIONS:
        raise ValueError("route file must be a supported route JSON payload")
    if payload.get("unresolved_facts"):
        # An unresolved route is a question, not a decision: it must never run, however it reached the replay.
        raise ValueError(
            f"route has unresolved facts ({', '.join(str(f) for f in payload['unresolved_facts'])}); "
            "answer them with --answer FACT=VALUE and route again"
        )
    fast_path = payload.get("fast_path")
    if fast_path is not None:
        task_type, facts = payload.get("task_type"), payload.get("facts")
        facts = {**OPTIONAL_FACT_DEFAULTS, **facts} if isinstance(facts, dict) else None
        if task_type not in TASK_TYPES or not isinstance(facts, dict) or set(facts) != set(FACTS):
            raise ValueError("fast-path route must carry a complete supported classification")
        if any(facts.get(name) not in values for name, values in FACTS.items()):
            raise ValueError("fast-path route contains invalid classification facts")
        level, risk_tier, _, _ = evaluate_rules(facts)
        if payload.get("effective_level") != level or payload.get("risk_tier") != risk_tier:
            raise ValueError("fast-path route classification does not match its facts")
        if task_type == "inspect" and (risk_tier != "standard" or LEVELS.index(level) > LEVELS.index(INSPECT_MAX_LEVEL)):
            raise ValueError("inspect fast path must be a standard L1-L2 read-only lookup")
        if fast_path != fast_path_for(task_type, level, risk_tier, facts, check_available=True):
            raise ValueError("fast-path route no longer qualifies for its declared fast path")
    if payload["schema_version"] >= 3:
        if payload.get("execution_strategy") != "direct" or not isinstance(payload.get("orchestration_eligible"), bool):
            raise ValueError("v3 route file must declare direct strategy and orchestration eligibility")
    platform = payload.get("platform")
    executable = {"codex": "codex", "claude-code": "claude", "antigravity": "agy"}.get(platform)
    if executable is None:
        raise ValueError("route file must target a supported platform")
    model_option = "-m" if platform == "codex" else "--model"
    steps = payload.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("route file must contain at least one execution step")
    mode = payload.get("mode")
    plan_path = None
    if mode == "two_stage" and len(steps) == 2:
        plan = steps[0].get("output") if isinstance(steps[0], dict) else None
        plan_path = plan.get("path") if isinstance(plan, dict) else None
        if not isinstance(plan_path, str) or not plan_path:
            raise ValueError("two-stage route file must declare its plan output")
    elif not (mode == "single" and len(steps) == 1):
        raise ValueError("route file mode does not match its execution steps")
    commands: list[list[str]] = []
    for index, step in enumerate(steps):
        command = step.get("command") if isinstance(step, dict) else None
        if not isinstance(command, list) or not command or command[0] != executable or not all(isinstance(arg, str) and arg for arg in command):
            raise ValueError("route file contains an invalid platform command")
        if not isinstance(step.get("model"), str) or step["model"] != command_model(command, model_option):
            raise ValueError("route file step model does not match its command")
        if plan_path is not None:
            access = "read" if index == 0 and payload["schema_version"] >= SCHEMA_VERSION else ("plan" if index == 0 else "edit")
        else:
            access = "edit" if payload.get("task_type") in CODE_CHANGE_TASK_TYPES else "read"
        validate_argv(
            platform, command, model=step["model"], effort=step.get("effort"), access=access,
            plan_path=plan_path if index == 0 else None, legacy=payload["schema_version"] < 6,
        )
        if payload["schema_version"] >= 6:  # older routes were written with older instruction texts
            validate_step_instructions(
                payload, index, command, plan_path, step.get("effort"), router=_THIS_MODULE or sys.modules.get("router")
            )
        commands.append(command)
    return commands, plan_path

def command_chain_from_payload(payload: object, cleanup_plan_dir: bool = False) -> str:
    """Return the already-classified plan/implement shell chain from a route JSON payload.

    This is the printable, replayable core of a route; the test/review/fix stages of a
    v6 ``pipeline`` block run only through scripts/pipeline.py.

    ``cleanup_plan_dir`` removes the two-stage plan directory after the chain runs,
    on both success and failure. It must only be set by a caller that just generated
    this route file for an immediate direct run (the plan dir was created for this
    run alone) -- never for a stored/user-supplied route file replayed later, whose
    plan artifacts the user may still want.
    """
    commands, plan_path = validated_commands(payload)
    if plan_path is None:
        return shlex.join(commands[0])
    plan_dir = shlex.quote(str(Path(plan_path).parent))
    stages = " && ".join(shlex.join(command) for command in commands)
    if not cleanup_plan_dir:
        return f"mkdir -p {plan_dir} && {stages}"
    # Clean up on both success and failure (rc preserved) -- unlike a plain
    # `&&` tail, this must not depend on every stage succeeding.
    return f"mkdir -p {plan_dir} && ({stages}; rc=$?; rm -rf {plan_dir}; exit $rc)"

def main(argv: list[str] | None = None) -> int:
    from cli import main as cli_main
    return cli_main(argv, router=_THIS_MODULE or sys.modules.get("router"))

if __name__ == "__main__":
    raise SystemExit(main())

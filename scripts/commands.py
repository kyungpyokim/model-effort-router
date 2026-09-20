"""CLI command generation and validation for Codex, Claude Code, and Antigravity."""

from __future__ import annotations

import json
import re
import shlex
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

if TYPE_CHECKING:
    from router import RouteResult

from policy import AGENT_NAME_RE, AGY_MODEL_RE, MODEL_RE, model_ok

from rules import CODE_CHANGE_TASK_TYPES, EFFORT_ORDER, LEVEL_NAMES, RISK_FLAGS, SECURITY_FLOOR_FLAGS

PLANNER_INSTRUCTIONS_TEMPLATE = """You are the planning stage of a two-stage plan-and-implement pipeline.
Analyse the request against the current repository state and produce a structured implementation plan.
Apply re0 and debloat principles: write the plan as a clean v0 specification without speculative boilerplate or process noise. Cut words, keep rules: each step must be concise, mechanistic, and load-bearing.
Write the plan as JSON to exactly this path: {plan_path}
Use this top-level shape:
{{"schema_version": 1, "analysis": {{"current_structure": [], "constraints": [], "affected_areas": [], "risks": []}}, "implementation_plan": {{"steps": [], "expected_files": [], "compatibility_requirements": []}}, "validation": {{"commands": [], "acceptance_criteria": [], "rollback_notes": []}}}}
Do not modify any repository file. Read-only analysis plus writing the single plan file is allowed.
Cross-check the request against the real repository before writing the plan.
Do not invoke the model-effort router recursively.
If the repository cannot be analysed safely, exit non-zero without writing the plan."""

IMPLEMENTER_INSTRUCTIONS_TEMPLATE = """You are the execution stage of a two-stage plan-and-implement pipeline.
A structured plan file is provided at: {plan_path}
Read the plan together with the original request and the current repository state first.
Apply re0 hygiene: leave the codebase cleaner than found, touch only what the plan requires, and remove scaffolding residue.
If the repository conflicts with the plan, stop and report the difference instead of forcing the plan through.
Do not make new design decisions yourself. Stop and return escalation evidence for the planner, as a final line that starts with ESCALATE and a colon, when you find a wider scope than planned, an architecture change, a public API change, a needed data migration, a security-boundary change, or a plan that no longer matches the code. Difficulty or uncertainty alone is not evidence.
Execute the planned changes, run validation.commands, satisfy acceptance_criteria, and apply rollback_notes when validation fails.
Do not blindly follow the plan when the repository state has moved on from what the planner saw.
Do not invoke the model-effort router recursively."""

AUTOBAHN_SCOPE_GUARD_INSTRUCTION = (
    "Isolate security/auth/payment sensitive boundaries; "
    "implement and verify safe scope first and document carved items."
)

AUTOBAHN_SCOPE_GUARD = f"Autobahn scope guard: {AUTOBAHN_SCOPE_GUARD_INSTRUCTION}"

MARKDOWN_AGENT_PLUGINS = {
    "claude-code": "claude-model-effort-router",
    "antigravity": "antigravity-model-effort-router",
}

LEGACY_PLANNER_PROMPT_PREFIX = "Produce an architectural refactoring plan.\nOriginal request:\n"

LEGACY_IMPLEMENTER_PROMPT_PREFIX = "Execute the prepared refactoring plan.\nOriginal request:\n"

PLAN_ROLE_PROMPT = "PLAN\nProduce the minimum implementation plan needed for this task."

DESIGN_ROLE_PROMPT = "DESIGN\nProduce the architecture/design plan needed for this task."

IMPLEMENT_ROLE_PROMPT = "IMPLEMENT\nImplement the approved plan without expanding scope."

REVIEW_ROLE_PROMPT = "REVIEW\nReview the implementation against the requirements and plan."

INSPECT_ROLE_PROMPT = "INSPECT\nAnswer the read-only lookup without widening scope."

PLANNER_PROMPT_PREFIX = f"{PLAN_ROLE_PROMPT}\nOriginal request:\n"

DESIGN_PROMPT_PREFIX = f"{DESIGN_ROLE_PROMPT}\nOriginal request:\n"

IMPLEMENTER_PROMPT_PREFIX = f"{IMPLEMENT_ROLE_PROMPT}\nOriginal request:\n"

CLAUDE_READ_TOOLS = ("Read", "Grep", "Glob")

MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/\-]*$")  # Codex and Claude ids

AGY_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()/:\-]*$")  # display names like "Gemini 3.1 Pro (High)"

AGENT_NAME_RE = re.compile(r"^[a-z0-9-]+$")

CODEX_CONFIG_KEYS = ("model_reasoning_effort", "developer_instructions")

def agent_name(level: str) -> str:
    return f"level-{level[1:]}-{LEVEL_NAMES[level]}"

def codex_agent_instructions(level: str) -> str:
    filename = f"{agent_name(level)}.toml"
    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent / "agents" / filename,
        here.parent.parent / "plugins" / "codex-model-effort-router" / "agents" / filename,
        here.parent / "agents" / filename,
    ]
    for candidate in candidates:
        if candidate.exists():
            return tomllib.loads(candidate.read_text(encoding="utf-8"))["developer_instructions"]
    raise FileNotFoundError(f"Codex agent profile not found: {filename}")

def markdown_agent_instructions(platform: str, level: str) -> str:
    """Return a level agent's markdown body so launchers work without the plugin installed."""
    plugin = MARKDOWN_AGENT_PLUGINS[platform]
    filename = f"{agent_name(level)}.md"
    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent.parent / plugin / "agents" / filename,
        here.parent.parent / "plugins" / plugin / "agents" / filename,
        here.parent.parent / "agents" / filename,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8").split("---", 2)[2].strip()
    raise FileNotFoundError(f"{platform} agent profile not found: {filename}")

def role_prompt_prefix(task_type: str) -> str:
    return {
        "design": DESIGN_PROMPT_PREFIX,
        "review": f"{REVIEW_ROLE_PROMPT}\nOriginal request:\n",
        "inspect": f"{INSPECT_ROLE_PROMPT}\nOriginal request:\n",
    }.get(task_type, IMPLEMENTER_PROMPT_PREFIX)

def _codex_exec_command(model: str, effort: str, instructions: str, prompt: str, interactive: bool, access: str = "edit") -> list[str]:
    options = [
        "-m", model,
        "-c", f"model_reasoning_effort={effort}",
        "-c", f"developer_instructions={json.dumps(instructions)}",
    ]
    if access == "read":
        options += ["--sandbox", "read-only"]
    return ["codex", *options, prompt] if interactive else ["codex", "exec", *options, prompt]

def claude_access_flags(access: str, plan_path: str | None = None) -> list[str]:
    """Permission flags for a non-interactive Claude stage.

    ``edit`` (implement/fix) auto-approves file edits. ``plan`` may write only the plan file and
    ``read`` may not write at all: dontAsk denies whatever would prompt, deny rules (which beat
    project allow rules) close Bash, the edit tools and MCP servers."""
    if access == "edit":
        return ["--permission-mode", "acceptEdits"]
    if access == "plan":
        if not plan_path or not plan_path.startswith("/") or "(" in plan_path or ")" in plan_path:
            raise ValueError("a plan stage needs an absolute plan path without parentheses")
        # Edit(//abs) is the absolute-path rule form and covers every built-in file-editing tool;
        # the Edit tool family cannot be denied here without denying the plan file itself.
        return [
            "--permission-mode", "dontAsk", "--allowedTools", *CLAUDE_READ_TOOLS, f"Edit(/{plan_path})",
            "--disallowedTools", "Bash", "NotebookEdit", "--strict-mcp-config",
        ]
    return [
        "--permission-mode", "dontAsk", "--allowedTools", *CLAUDE_READ_TOOLS,
        "--disallowedTools", "Edit", "Write", "NotebookEdit", "Bash", "--strict-mcp-config",
    ]

def _claude_print_command(model: str, effort: str | None, prompt: str, access: str = "read", plan_path: str | None = None) -> list[str]:
    command = ["claude", "-p", "--model", model]
    if effort:
        command += ["--effort", effort]
    # `--` ends the variadic tool lists so the prompt is never read as a tool name.
    return [*command, *claude_access_flags(access, plan_path), "--", prompt]

def _agy_prompt_command(model: str, prompt: str) -> list[str]:
    return ["agy", "--model", model, "--prompt", prompt]

def _single_stage_command(result: RouteResult, task: str, interactive: bool) -> list[str]:
    has_security_flag = any(result.risk_flags.get(f) for f in SECURITY_FLOOR_FLAGS)
    if result.platform == "codex":
        stage = result.stages[0]
        instructions = codex_agent_instructions(result.level)
        if has_security_flag:
            instructions += f"\n{AUTOBAHN_SCOPE_GUARD}"
        instructions = f"{instructions}\n\n{verification_handoff_instructions(result)}"
        prompt = f"{role_prompt_prefix(result.task_type)}{task}"
        access = "edit" if result.task_type in CODE_CHANGE_TASK_TYPES else "read"
        return _codex_exec_command(stage["model"], stage["effort"], instructions, prompt, interactive, access)
    return shell_command(result, task, interactive)

def shell_command(result: RouteResult, task: str, interactive: bool) -> list[str]:
    """Single-stage launcher for Claude Code and Antigravity.

    Level instructions are embedded instead of passed as ``--agent``: without the
    plugin installed, claude exits with "agent not found" and agy silently ignores it.
    """
    task = f"{role_prompt_prefix(result.task_type)}{task}"
    if any(result.risk_flags.get(f) for f in SECURITY_FLOOR_FLAGS):
        task = f"[{AUTOBAHN_SCOPE_GUARD}]\n\n{task}"
    task = f"{task}\n\n{verification_handoff_instructions(result)}"
    if result.platform not in MARKDOWN_AGENT_PLUGINS:
        raise ValueError("use stage_commands for codex results")
    # Instructions lead the prompt so the Agent tool path (which reuses the prompt) keeps them.
    prompt = f"{markdown_agent_instructions(result.platform, result.level)}\n\n{task}"
    if result.platform == "claude-code":
        access = "edit" if result.task_type in CODE_CHANGE_TASK_TYPES else "read"
        if not interactive:
            return _claude_print_command(result.model, result.effort, prompt, access)
        base = ["claude", "--model", result.model]
        if result.effort:
            base += ["--effort", str(result.effort)]
        if access == "read":
            base += [*claude_access_flags("read"), "--"]
        return base + [prompt]
    return ["agy", "--model", result.model, *(["--prompt-interactive", prompt] if interactive else ["--prompt", prompt])]

def stage_command(platform: str, stage: dict, instructions: str, prompt: str, access: str = "read", plan_path: str | None = None) -> list[str]:
    """One non-interactive exec/print argv for a stage with explicit instructions.

    ``access`` (read / plan / edit) is enforced by Claude Code's permission flags; Codex and
    Antigravity keep their own sandboxing."""
    if platform == "codex":
        return _codex_exec_command(stage["model"], stage["effort"], instructions, prompt, interactive=False, access=access)
    if platform == "claude-code":
        return _claude_print_command(stage["model"], stage["effort"], f"{instructions}\n\n{prompt}", access, plan_path)
    return _agy_prompt_command(stage["model"], f"{instructions}\n\n{prompt}")

def refuse_interactive_two_stage(result: RouteResult, interactive: bool) -> None:
    if interactive and result.mode == "two_stage":
        raise ValueError(
            "--interactive is single-stage only; this route is two-stage (plan -> implement). "
            "Run without --interactive so the pipeline runs the plan, test gate and review"
        )

def stage_commands(result: RouteResult, task: str, interactive: bool = False) -> list[list[str]]:
    """Build one argv per execution stage. Two-stage runs are always exec/print sessions
    and refuse ``interactive``."""
    refuse_interactive_two_stage(result, interactive)
    if result.mode != "two_stage":
        return [_single_stage_command(result, task, interactive)]
    plan_path = str(Path(result.plan_dir) / "plan.json")
    planner, implementer = result.stages
    has_security_flag = any(result.risk_flags.get(f) for f in SECURITY_FLOOR_FLAGS)
    instructions = PLANNER_INSTRUCTIONS_TEMPLATE.format(plan_path=plan_path)
    if has_security_flag:
        instructions += f"\n{AUTOBAHN_SCOPE_GUARD}"
    plan_prompt = f"{PLANNER_PROMPT_PREFIX}{task}\n\nWrite the plan JSON to exactly: {plan_path}\n"
    execute_instructions = IMPLEMENTER_INSTRUCTIONS_TEMPLATE.format(plan_path=plan_path)
    if has_security_flag:
        execute_instructions += f"\n{AUTOBAHN_SCOPE_GUARD}"
    execute_instructions = f"{execute_instructions}\n\n{verification_handoff_instructions(result)}"
    execute_prompt = f"{IMPLEMENTER_PROMPT_PREFIX}{task}\n\nPlan file to read first: {plan_path}\n"
    return [
        stage_command(result.platform, planner, instructions, plan_prompt, "plan", plan_path),
        stage_command(result.platform, implementer, execute_instructions, execute_prompt, "edit"),
    ]

def command_chain(result: RouteResult, task: str, keep_plan: bool = False, interactive: bool = False) -> str | None:
    """Assemble a success-dependent shell chain. Returns None when nothing to print."""
    commands = stage_commands(result, task, interactive)
    parts = [shlex.join(command) for command in commands]
    if result.mode != "two_stage":
        return parts[0]
    prefix = f"mkdir -p {shlex.quote(str(result.plan_dir))}"
    cleanup = "" if keep_plan else f" && rm -rf {shlex.quote(str(result.plan_dir))}"
    return f"{prefix} && {' && '.join(parts)}{cleanup}"

def command_model(command: list[str], option: str) -> str | None:
    """Return the one model selected by a generated platform command."""
    models: list[str] = []
    prefix = f"{option}="
    for index, value in enumerate(command):
        if value == option and index + 1 < len(command):
            models.append(command[index + 1])
        elif value.startswith(prefix):
            models.append(value[len(prefix):])
    return models[0] if len(models) == 1 else None

def validate_argv(
    platform: str, command: list[str], *, model: str | None = None, effort: str | None = None,
    access: str | None = None, plan_path: str | None = None, legacy: bool = False,
) -> None:
    """Accept only argv shapes this router generates; refuse every other flag or override.

    The last element is the prompt. Claude commands of a v6 route must equal the generated
    argv for the step's model, effort and access level (permission flags included); routes
    older than v6 predate permission flags and may only carry the old ``--agent`` form."""
    options, i = command[1:-1], 0

    def fail(reason: str) -> NoReturn:
        raise ValueError(f"route file command is not a router-generated {platform} command ({reason})")

    if platform == "codex":
        if options[:1] == ["exec"]:
            options = options[1:]
        models = sandboxes = 0
        while i < len(options):
            flag, value = options[i], options[i + 1] if i + 1 < len(options) else None
            key, sep, setting = (value or "").partition("=")
            if flag == "-m" and model_ok(platform, value):
                models += 1
            elif flag == "-c" and sep and key in CODEX_CONFIG_KEYS and (key != "model_reasoning_effort" or setting in EFFORT_ORDER):
                pass
            elif flag == "--sandbox" and access == "read" and value == "read-only":
                sandboxes += 1
            else:
                fail(f"unexpected option {flag}")
            i += 2
        if models != 1:
            fail("expected exactly one model")
        if access == "read" and sandboxes != 1:
            fail("read-only stages require exactly one read-only sandbox")
        return
    if platform == "antigravity":
        if legacy and options[:1] == ["--agent"] and len(options) > 1 and AGENT_NAME_RE.match(options[1]):
            options = options[2:]
        if len(options) != 3 or options[0] != "--model" or not model_ok(platform, options[1]) or options[2] not in ("--prompt", "--prompt-interactive"):
            fail("unexpected option")
        return
    if not model_ok(platform, model):
        fail("bad model")
    tail = [*(["--effort", effort] if effort else [])]
    if not legacy:
        try:
            expected = [["claude", "-p", "--model", model, *tail, *claude_access_flags(access or "read", plan_path), "--"]]
            if access == "read":
                expected.append(["claude", "--model", model, *tail, *claude_access_flags("read"), "--"])
            else:
                expected.append(["claude", "--model", model, *tail])
        except ValueError as exc:
            fail(str(exc))
        if command[:-1] not in expected:
            fail("flags differ from the generated command")
        return
    seen_model = False
    while i < len(options):
        flag = options[i]
        if flag in ("-p", "--print"):
            i += 1
        elif flag == "--agent" and i + 1 < len(options) and AGENT_NAME_RE.match(options[i + 1]):
            i += 2
        elif flag == "--model" and i + 1 < len(options) and options[i + 1] == model and not seen_model:
            seen_model = True
            i += 2
        elif flag == "--effort" and i + 1 < len(options) and options[i + 1] in EFFORT_ORDER:
            i += 2
        else:
            fail(f"unexpected option {flag}")
    if not seen_model:
        fail("expected a model")

def handoff_text(task_type: str, level: str, risk_flags: dict[str, bool], mode: str) -> str:
    checks = verification_recommendations(task_type, level, risk_flags, mode)["recommended"]
    check_lines = "\n".join(f"- {check['id']}: {check['reason']}" for check in checks)
    return (
        "Verification handoff:\n"
        f"Recommended checks:\n{check_lines}\n"
        "Select and run only existing repository checks that apply. "
        "Report each recommended check's result or why it was not run. "
        "Do not report an unrun check as passed."
    )

def verification_recommendations(task_type: str, level: str, risk_flags: dict[str, bool], mode: str) -> dict[str, list[dict[str, str]]]:
    """Return repository-agnostic verification guidance for an already selected route."""
    has_security_risk = any(risk_flags.get(flag, False) for flag in SECURITY_FLOOR_FLAGS)
    checks = (
        (
            "focused_tests",
            task_type in {"implementation", "local_refactoring", "architectural_refactoring"},
            "Code changes need focused regression coverage.",
            "The route does not request a code change.",
        ),
        (
            "plan_validation",
            mode == "two_stage",
            "The planner artifact should be validated before execution.",
            "The route has no planner artifact.",
        ),
        (
            "contract_review",
            task_type in {"design", "review"} or risk_flags.get("public_api_change", False),
            "The route includes a design, review, or public API contract change.",
            "The route has no indicated external contract change.",
        ),
        (
            "security_review",
            has_security_risk,
            "A security, authentication, authorization, or payment risk is active.",
            "No security, authentication, authorization, or payment risk is active.",
        ),
        (
            "migration_safety",
            risk_flags.get("data_migration", False),
            "A data migration risk is active.",
            "No data migration risk is active.",
        ),
        (
            "broad_regression",
            level == "L5",
            "The effective level requires broad regression coverage.",
            "The effective level remains within a bounded scope.",
        ),
    )
    recommended: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for check_id, applies, recommendation_reason, skipped_reason in checks:
        target = recommended if applies else skipped
        target.append({"id": check_id, "reason": recommendation_reason if applies else skipped_reason})
    return {"recommended": recommended, "skipped": skipped}

def verification_handoff_instructions(result: RouteResult) -> str:
    """Format already-selected verification guidance for an executor prompt."""
    return handoff_text(result.task_type, result.level, result.risk_flags, result.mode)

def expected_stage_text(payload: dict, index: int, plan_path: str | None, router: object | None = None) -> tuple[str, str, str]:
    """What a router-generated step must contain: (instructions, prompt head after them, prompt tail).

    Codex carries the instructions in ``developer_instructions``; Claude Code and Antigravity embed
    them at the front of the prompt. Only the task text between head and tail is free."""
    platform, level, task_type, mode = payload["platform"], payload["effective_level"], payload["task_type"], payload["mode"]
    declared = payload.get("risk_flags") or []
    if not isinstance(declared, list) or not all(isinstance(flag, str) and flag in RISK_FLAGS for flag in declared):
        raise ValueError("risk_flags must be a list of known risk flag names")
    flags = {flag: flag in declared for flag in RISK_FLAGS}
    secure = any(flags[flag] for flag in SECURITY_FLOOR_FLAGS)
    guard = f"\n{AUTOBAHN_SCOPE_GUARD}" if secure else ""
    handoff = handoff_text(task_type, level, flags, mode)
    if router is None:
        router = sys.modules.get("router")
    schema_version = getattr(router, "SCHEMA_VERSION", 7)
    codex_instructions = getattr(router, "codex_agent_instructions", codex_agent_instructions)
    markdown_instructions = getattr(router, "markdown_agent_instructions", markdown_agent_instructions)

    legacy = payload["schema_version"] < schema_version
    if mode == "two_stage":
        if index == 0:
            prefix = LEGACY_PLANNER_PROMPT_PREFIX if legacy else PLANNER_PROMPT_PREFIX
            return PLANNER_INSTRUCTIONS_TEMPLATE.format(plan_path=plan_path) + guard, prefix, f"\n\nWrite the plan JSON to exactly: {plan_path}\n"
        return (
            f"{IMPLEMENTER_INSTRUCTIONS_TEMPLATE.format(plan_path=plan_path)}{guard}\n\n{handoff}",
            LEGACY_IMPLEMENTER_PROMPT_PREFIX if legacy else IMPLEMENTER_PROMPT_PREFIX,
            f"\n\nPlan file to read first: {plan_path}\n",
        )
    if platform == "codex":
        return f"{codex_instructions(level)}{guard}\n\n{handoff}", "" if legacy else role_prompt_prefix(task_type), ""
    head = f"[{AUTOBAHN_SCOPE_GUARD}]\n\n" if secure else ""
    if not legacy:
        head += role_prompt_prefix(task_type)
    return markdown_instructions(platform, level), head, f"\n\n{handoff}"

def validate_step_instructions(
    payload: dict, index: int, command: list[str], plan_path: str | None, effort: str | None, router: object | None = None,
) -> None:
    """A v6 route's stage instructions, scope guard and effort must be the generated ones.

    The argv grammar accepts any ``developer_instructions`` text; without this a route file could
    rewrite a stage's whole prompt (drop the scope guard or the verification handoff)."""
    def fail(reason: str) -> NoReturn:
        raise ValueError(f"route file step {index + 1} does not carry the generated instructions ({reason})")

    try:
        instructions, head, tail = expected_stage_text(payload, index, plan_path, router=router)
    except (OSError, KeyError, TypeError, IndexError, ValueError) as exc:
        # Not evidence of tampering: the data needed to verify the step is missing or broken here.
        raise ValueError(f"route file step {index + 1} cannot be verified on this install ({type(exc).__name__}: {exc})") from exc
    prompt = command[-1]
    if payload["platform"] == "codex":
        settings = [command[i + 1].partition("=") for i, flag in enumerate(command[:-1]) if flag == "-c"]
        found = [value for key, _, value in settings if key == "developer_instructions"]
        efforts = [value for key, _, value in settings if key == "model_reasoning_effort"]
        try:
            actual = json.loads(found[0]) if len(found) == 1 else None
        except json.JSONDecodeError:
            actual = None
        if actual != instructions:
            fail("developer_instructions differ or repeat")
        if efforts != [effort]:
            fail("reasoning effort differs from the step")
        if not prompt.startswith(head) or not prompt.endswith(tail):
            fail("prompt does not carry the stage task prefix and plan-file suffix")
        return
    if not prompt.startswith(f"{instructions}\n\n{head}") or not prompt.endswith(tail):
        fail("prompt does not carry the stage instructions")

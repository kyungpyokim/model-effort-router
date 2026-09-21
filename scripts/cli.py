"""CLI parsing and interactive terminal prompts for model-effort router."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from classifier import Classification
    from router import RouteResult

import route_reuse
from classifier import (
    CLASSIFIER_SCHEMA,
    CLASSIFIER_TIMEOUT_SECONDS,
    DETECT_TIMEOUT_SECONDS,
    EXIT_NEEDS_ANSWER,
    FACT_QUESTIONS,
    FALLBACK_TASK_TYPE,
    apply_answers,
    classifier_prompt,
    classify_task,
    read_classification_file,
    settleable,
)
from commands import (
    command_chain,
    shell_command,
    stage_commands,
)
from policy import load_config, positive_finite_float
from rules import (
    FACTS,
    LEVELS,
    TASK_TYPES,
    TIER_LEVEL,
)


def _prompt_axis(label: str, choices: tuple[str, ...], default: str | None = None) -> str:
    menu = "/".join(choices)
    hint = f" [{default}]" if default else ""
    while True:
        sys.stderr.write(f"  {label} ({menu}){hint}: ")
        sys.stderr.flush()
        raw = input().strip()
        if not raw and default:
            return default
        for choice in choices:
            if raw.lower() == choice.lower():
                return choice
        sys.stderr.write(f"    '{raw}' is not a valid {label}\n")


def prompt_unresolved(classification: Classification) -> Classification:
    sys.stderr.write("Some facts could not be settled from the task or the repository; please answer:\n")
    answers = {}
    for fact in classification.unresolved:
        sys.stderr.write(f"{FACT_QUESTIONS[fact]}\n")
        answers[fact] = _prompt_axis(fact, tuple(v for v in FACTS[fact] if v != "unknown" and settleable(classification, fact, v)))
    return apply_answers(classification, answers)[0]


def parse_answer(value: str) -> tuple[str, str]:
    fact, sep, answer = value.partition("=")
    if not sep or fact not in FACTS or answer not in FACTS[fact] or answer == "unknown":
        raise argparse.ArgumentTypeError(f"--answer expects FACT=VALUE with a known fact and an explicit value; got {value!r}")
    return fact, answer


def prompt_manual_classification(fallback: Classification) -> tuple[Classification, bool]:
    from classifier import Classification as Cls
    sys.stderr.write(f"Semantic preflight failed ({fallback.reason}); choose routing axes manually.\n")
    task_type = _prompt_axis("task_type", TASK_TYPES, FALLBACK_TASK_TYPE)
    level = _prompt_axis("level", (*LEVELS, "critical"))
    is_critical = level == "critical"
    resolved_level = TIER_LEVEL if is_critical else level
    classification = Cls(
        task_type=task_type,
        level=resolved_level,
        risk_flags=dict(fallback.risk_flags),
        reason=f"Manual classification after preflight failure ({fallback.reason})",
        source="manual",
    )
    return classification, is_critical


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
    parser.add_argument("--repo-aware", action="store_true", help="Let the classifier read the repository in its one pass (the same model, no stronger classifier)")
    parser.add_argument(
        "--print-classifier-prompt",
        action="store_true",
        help="Print the classifier prompt and JSON schema for an external classifier, then exit",
    )
    parser.add_argument(
        "--classification-file",
        metavar="PATH",
        help="Route from externally produced classifier JSON (a path, or - for stdin) instead of "
        "spawning a classifier; a primary/lookup envelope folds one bounded same-model lookup into the first reply",
    )
    parser.add_argument(
        "--session", default=None, metavar="KEY",
        help=f"Reuse this session's stored classification for follow-up tasks (also {route_reuse.SESSION_ENV}); "
        "a workspace change, expiry, an earlier re-plan, or a new operation, scope or risk reclassifies",
    )
    parser.add_argument(
        "--answer", action="append", default=[], type=parse_answer, metavar="FACT=VALUE",
        help="Answer a question about a fact the classifier could not settle (repeatable); "
        "it only fills a fact that is still unknown",
    )
    parser.add_argument("--no-reuse", action="store_true", help="Classify again even when the session has a reusable route")
    parser.add_argument("--critical", action="store_true", help="Force the critical risk tier (L5 with maximum planning/judging effort)")
    parser.add_argument("--classifier-timeout", type=positive_finite_float, default=CLASSIFIER_TIMEOUT_SECONDS)
    parser.add_argument("--detect-antigravity-models", action="store_true")
    parser.add_argument("--detect-timeout", type=positive_finite_float, default=DETECT_TIMEOUT_SECONDS)
    parser.add_argument("--available-models-file", type=Path)
    parser.add_argument("--format", choices=("json", "text", "command"), default="text")
    parser.add_argument("--interactive", action="store_true", help="Build an interactive-session command (single-stage only)")
    parser.add_argument(
        "--cleanup-plan-dir",
        action="store_true",
        help="Remove the two-stage plan directory after the chain runs; only for a route "
        "file just generated for this direct run, never for a stored/user route file",
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="Never prompt for manual axes when the preflight fails; emit the safe fallback route and exit non-zero",
    )
    args = parser.parse_args(argv)
    if args.route_file:
        task_options = {
            "--platform", "--config", "--level", "--task-type", "--keep-plan",
            "--classifier-timeout", "--detect-antigravity-models", "--detect-timeout",
            "--available-models-file", "--format", "--interactive", "--no-prompt", "--repo-aware", "--critical",
            "--print-classifier-prompt", "--classification-file", "--session", "--no-reuse", "--answer",
        }
        if args.task or any(option in argv for option in task_options):
            parser.error("--route-file cannot be combined with task-routing options")
    elif args.cleanup_plan_dir:
        parser.error("--cleanup-plan-dir requires --route-file")
    elif args.print_classifier_prompt:
        if not args.task:
            parser.error("task is required with --print-classifier-prompt")
    elif not args.task or not args.platform:
        parser.error("task and --platform are required unless --route-file is used")
    return args


def main(argv: list[str] | None = None, router: object | None = None) -> int:
    if router is None:
        router = sys.modules.get("router")
    if router is None:
        import router
    args = parse_args(argv or sys.argv[1:])
    if args.route_file:
        try:
            payload = json.loads(args.route_file.read_text(encoding="utf-8"))
            chain = router.command_chain_from_payload(payload, cleanup_plan_dir=args.cleanup_plan_dir)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"invalid route file: {exc}", file=sys.stderr)
            return 2
        print(chain)
        return 0
    if args.print_classifier_prompt:
        print(router.classifier_prompt(args.task, Path.cwd() if args.repo_aware else None))
        print(f"\nReturn JSON matching this schema:\n{json.dumps(router.CLASSIFIER_SCHEMA)}")
        return 0
    external = None
    if args.classification_file:
        try:
            external = router.read_classification_file(args.classification_file)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            print(f"invalid classification file: {exc}", file=sys.stderr)
            return 2
    config = router.load_config(args.config or router.default_config_path())
    explicit_task_type = None if args.task_type == "auto" else args.task_type
    available = None
    if args.available_models_file:
        available = [line.strip() for line in args.available_models_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    elif args.detect_antigravity_models:
        try:
            available = router.read_available_models(timeout=args.detect_timeout)
        except RuntimeError as exc:
            print(f"model detection failed ({exc}); using configured fallbacks", file=sys.stderr)
    manual_bypass = explicit_task_type is not None and (args.critical or args.level is not None)

    classification = external
    session = args.session or os.environ.get(route_reuse.SESSION_ENV)
    reuse_info = None
    stored = None
    if session and not manual_bypass and classification is None and not args.no_reuse:
        classification, stored, why = router.load_reused_classification(session, os.getcwd(), args.task, explicit_task_type)
        reuse_info = {"session": session, "reused": classification is not None, **({"reason": why} if why else {})}
    elif session:
        reuse_info = {"session": session, "reused": False, "reason": "reuse skipped (explicit classification, pins, or --no-reuse)"}
    prompted_critical = False
    if not manual_bypass and classification is None:
        classification = router.classify_task(
            args.task, args.platform, args.classifier_timeout,
            repo_aware=args.repo_aware, available_models=available,
        )
        if classification.source == "fallback" and not args.no_prompt and sys.stdin.isatty():
            try:
                classification, prompted_critical = router.prompt_manual_classification(classification)
            except (EOFError, KeyboardInterrupt):
                sys.stderr.write("\nmanual classification aborted; using safe fallback\n")
    ignored_answers: list[str] = []
    if classification is not None and args.answer:
        classification, ignored_answers = router.apply_answers(classification, dict(args.answer))
        if ignored_answers:
            sys.stderr.write(f"ignored answers for facts that are not unknown: {', '.join(ignored_answers)}\n")
    if classification is not None and classification.unresolved and not args.no_prompt and sys.stdin.isatty():
        try:
            classification = router.prompt_unresolved(classification)
        except (EOFError, KeyboardInterrupt):
            sys.stderr.write("\nquestions unanswered; the facts stay unknown\n")

    try:
        result = router.route(
            args.task,
            args.platform,
            config,
            args.level,
            explicit_task_type,
            available,
            classifier=(lambda _task: classification) if classification is not None else None,
            repo_aware=args.repo_aware,
            critical=args.critical or prompted_critical,
            check_available=bool((os.environ.get(router.TEST_COMMAND_ENV) or "").strip()),
        )
        router.refuse_interactive_two_stage(result, args.interactive)
    except ValueError as exc:
        print(f"routing failed: {exc}", file=sys.stderr)
        return 2
    if session and result.source not in ("fallback", "manual") and not result.unresolved:
        delegability = classification.delegability if classification is not None else 0
        route_reuse.save_record(
            session, os.getcwd(), router.session_record(result, delegability),
            saved_at=stored.get("saved_at") if reuse_info and reuse_info["reused"] else None,
            reuses=int(stored.get("reuses", 0)) + 1 if reuse_info and reuse_info["reused"] else 0,
        )
    if result.source == "fallback":
        print(
            "Semantic preflight failed; safe fallback applied "
            f"({result.task_type} / {result.level}); pin --task-type/--level or rerun on a terminal to choose",
            file=sys.stderr,
        )
    if args.format == "json":
        payload = router.result_payload(result, router.stage_commands(result, args.task, args.interactive), args.task)
        if reuse_info:
            payload["reuse"] = reuse_info
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.format == "command":
        chain = router.command_chain(result, args.task, keep_plan=args.keep_plan, interactive=args.interactive)
        print(chain if chain is not None else shlex.join(router.shell_command(result, args.task, args.interactive)))
    else:
        stages_text = " -> ".join(
            f"{stage['role']}={stage['model']}/{stage['effort'] or ('embedded' if result.platform == 'antigravity' else 'none')}"
            for stage in result.stages
        )
        active_flags = [flag for flag, active in result.risk_flags.items() if active]
        print(f"{result.level} ({result.level_name}) | tier={result.risk_tier} | type={result.task_type} | mode={result.mode}")
        print(f"stages: {stages_text}")
        print("rules: " + (", ".join(result.matched_rules) or "none (base level)"))
        print("risk flags: " + (", ".join(active_flags) if active_flags else "none"))
        if reuse_info:
            print("route reuse: " + ("reused" if reuse_info["reused"] else f"reclassified ({reuse_info.get('reason', '')})"))
        if result.unresolved:
            print("unresolved facts (no rule matched them): " + ", ".join(result.unresolved))
        print("reason: " + "; ".join(result.rationale))
        if result.plan_dir:
            print(f"plan dir: {result.plan_dir}")
    if result.unresolved:
        sys.stderr.write("Unresolved facts (answer with --answer FACT=VALUE, or on a terminal when prompted):\n")
        for fact in result.unresolved:
            sys.stderr.write(f"  {fact}: {FACT_QUESTIONS[fact]} [{'/'.join(v for v in FACTS[fact] if v != 'unknown')}]\n")
    if result.source == "fallback":
        return 1
    return EXIT_NEEDS_ANSWER if result.unresolved else 0

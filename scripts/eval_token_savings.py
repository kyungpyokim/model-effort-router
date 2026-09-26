#!/usr/bin/env python3
"""Measure Codex token usage for corpus tasks at routed and max-level profiles."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = str(BUNDLE_ROOT / "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import router  # noqa: E402
from benchmark_corpus import GOLDEN_BENCHMARK_CASES  # noqa: E402
from eval_router_performance import _base_facts, _route_profile  # noqa: E402

CONFIG = router.load_config(BUNDLE_ROOT / "config" / "model-map.json")
CALL_TIMEOUT_SECONDS = 120
USAGE_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens")


def parse_usage(stdout: str) -> dict | None:
    """Return the latest complete-turn usage from Codex's JSON event stream."""
    usage = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            usage = event["usage"]
    required = ("input_tokens", "output_tokens")
    if usage is None or any(not isinstance(usage.get(key), int) for key in required):
        return None
    parsed = {key: usage.get(key) if isinstance(usage.get(key), int) else 0 for key in USAGE_FIELDS}
    if not isinstance(usage.get("total_tokens"), int):
        parsed["total_tokens"] = parsed["input_tokens"] + parsed["output_tokens"]
    return parsed


def executor_profile(profile: dict) -> tuple[str, str | None]:
    """Use the final stage (the task executor) when a route includes planning."""
    stages = profile.get("stages")
    if not stages or "error" in profile:
        raise ValueError(f"cannot measure route profile: {profile}")
    model, effort = stages[-1]
    return model, effort


def get_profile(case, level: str) -> tuple[str, str | None]:
    facts = {**_base_facts(), **case.facts}
    classification = router.Classification(
        task_type=case.task_type,
        level=level,
        risk_flags=router.risk_flags_from_facts(facts),
        reason="token measurement corpus label",
        source="benchmark",
        risk_tier=case.expected_tier,
        facts=facts,
    )
    profile = _route_profile(
        CONFIG, "codex", case.task, classification, case.expected_tier == "critical",
    )
    return executor_profile(profile)


def highest_allowed_profile(case) -> tuple[str, tuple[str, str | None]]:
    """Return the highest router-accepted level for this task type and risk tier."""
    for level in reversed(router.LEVELS):
        try:
            return level, get_profile(case, level)
        except ValueError:
            continue
    raise ValueError(f"no allowed Codex profile for corpus case {case.name}")


def corpus_rows(case_names: tuple[str, ...] = (), limit: int | None = None) -> list[dict]:
    selected = [case for case in GOLDEN_BENCHMARK_CASES if not case_names or case.name in case_names]
    if limit is not None:
        selected = selected[:limit]
    rows = []
    for case in selected:
        baseline_level, baseline_profile = highest_allowed_profile(case)
        rows.append({
            "name": case.name,
            "task": case.task,
            "expected_level": case.expected_level,
            "risk_tier": case.expected_tier,
            "routed_profile": get_profile(case, case.expected_level),
            "baseline_level": baseline_level,
            "baseline_profile": baseline_profile,
        })
    return rows


def _prompt(task: str) -> str:
    return (
        "Give a concise answer to this task. Do not access or modify files, run commands, "
        "or ask follow-up questions.\n\nTask:\n" + task
    )


def run_live_codex_call(model: str, effort: str | None, prompt: str) -> dict:
    cmd = [
        "codex", "exec", "-m", model,
        "--skip-git-repo-check", "--ephemeral", "--sandbox", "read-only", "--json",
    ]
    if effort:
        cmd += ["-c", f'model_reasoning_effort="{effort}"']
    cmd.append(prompt)
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, text=True, capture_output=True, timeout=CALL_TIMEOUT_SECONDS, cwd=str(BUNDLE_ROOT),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timed out after {CALL_TIMEOUT_SECONDS}s"}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}

    elapsed_ms = round((time.monotonic() - started) * 1000)
    usage = parse_usage(proc.stdout)
    return {
        "ok": proc.returncode == 0 and usage is not None,
        **(usage or {key: None for key in USAGE_FIELDS}),
        "elapsed_ms": elapsed_ms,
        "error": proc.stderr.strip().splitlines()[-1] if proc.returncode != 0 and proc.stderr.strip() else (
            "Codex response did not include complete token usage" if usage is None else ""
        ),
    }


def _has_usage(result: dict) -> bool:
    return result.get("ok") is True and isinstance(result.get("total_tokens"), int)


def summarize(cases: list[dict]) -> dict:
    paired = [case for case in cases if _has_usage(case["routed"]) and _has_usage(case["baseline"])]
    routed_input = sum(case["routed"]["input_tokens"] for case in paired)
    baseline_input = sum(case["baseline"]["input_tokens"] for case in paired)
    routed_output = sum(case["routed"]["output_tokens"] for case in paired)
    baseline_output = sum(case["baseline"]["output_tokens"] for case in paired)
    routed_total = sum(case["routed"]["total_tokens"] for case in paired)
    baseline_total = sum(case["baseline"]["total_tokens"] for case in paired)
    return {
        "total_cases": len(cases),
        "paired_cases": len(paired),
        "failed_pairs": len(cases) - len(paired),
        "routed_input_tokens": routed_input,
        "baseline_input_tokens": baseline_input,
        "routed_output_tokens": routed_output,
        "baseline_output_tokens": baseline_output,
        "routed_total_tokens": routed_total,
        "baseline_total_tokens": baseline_total,
        "token_savings": baseline_total - routed_total,
        "token_savings_pct": round((baseline_total - routed_total) / baseline_total * 100, 2) if baseline_total else None,
        "baseline_definition": "highest level accepted by router for the same task type and risk tier",
        "measurement_scope": "single executor response; excludes classifier, planner, and reviewer calls",
    }


def measure(rows: list[dict]) -> list[dict]:
    results = []
    for index, row in enumerate(rows, start=1):
        print(f"[{index}/{len(rows)}] {row['name']}", file=sys.stderr, flush=True)
        prompt = _prompt(row["task"])
        routed_profile = row["routed_profile"]
        baseline_profile = row["baseline_profile"]
        routed = run_live_codex_call(*routed_profile, prompt)
        if routed_profile == baseline_profile:
            baseline = dict(routed)
        else:
            baseline = run_live_codex_call(*baseline_profile, prompt)
        results.append({**row, "routed": routed, "baseline": baseline})
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Make real Codex calls; each pair uses up to two calls")
    parser.add_argument("--limit", type=int, help="Measure only the first N corpus cases")
    parser.add_argument("--case", action="append", dest="case_names", help="Measure a named case; repeat to select more")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if args.limit is not None and args.case_names:
        parser.error("--limit and --case cannot be combined")
    known = {case.name for case in GOLDEN_BENCHMARK_CASES}
    if unknown := sorted(set(args.case_names or ()) - known):
        parser.error(f"unknown --case: {', '.join(unknown)}")

    rows = corpus_rows(tuple(args.case_names or ()), args.limit)
    if not args.live:
        result = {"live": False, "summary": None, "cases": rows}
    else:
        print(f"Running up to {len(rows) * 2} Codex calls; identical profiles are measured once.", file=sys.stderr)
        measured = measure(rows)
        result = {"live": True, "summary": summarize(measured), "cases": measured}
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif not args.live:
        for row in rows:
            print(f"{row['name']}: routed={row['routed_profile']} baseline-{row['baseline_level']}={row['baseline_profile']}")
        print("Dry run only. Add --live to collect Codex-reported token usage.")
    else:
        summary = result["summary"]
        print(
            f"Paired cases: {summary['paired_cases']}/{summary['total_cases']}; "
            f"routed {summary['routed_total_tokens']:,} tokens vs max-allowed {summary['baseline_total_tokens']:,}; "
            f"saved {summary['token_savings']:,} ({summary['token_savings_pct']}%)."
        )
        if summary["failed_pairs"]:
            print(f"Failed pairs excluded: {summary['failed_pairs']}")
    return 0 if not args.live or result["summary"]["paired_cases"] == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())

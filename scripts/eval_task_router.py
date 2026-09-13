#!/usr/bin/env python3
"""Measure real token usage per task-router agent (codex-task-router + claude-task-router).

Runs one minimal real call per agent and reports the token usage the CLI itself
reports, so you can confirm the intended model/effort is actually what gets
billed. Dry-run by default; costs real API usage with --live.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

PROMPT = "Reply with exactly the single word OK. Do not explain."
BUNDLE_ROOT = Path(__file__).resolve().parent.parent
CODEX_AGENTS_DIR = BUNDLE_ROOT / "plugins" / "codex-task-router" / "agents"
CLAUDE_AGENTS_DIR = BUNDLE_ROOT / "plugins" / "claude-task-router" / "agents"
CLAUDE_BUDGET_USD = "0.05"


@dataclass(frozen=True)
class AgentCase:
    platform: str
    name: str
    model: str
    effort: str | None


def load_codex_agents() -> list[AgentCase]:
    cases = []
    for path in sorted(CODEX_AGENTS_DIR.glob("*.toml")):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        cases.append(AgentCase("codex", path.stem, data["model"], data.get("model_reasoning_effort")))
    return cases


def load_claude_agents() -> list[AgentCase]:
    cases = []
    for path in sorted(CLAUDE_AGENTS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        match = re.search(r"^model:\s*(\S+)\s*$", text, re.MULTILINE)
        if not match:
            continue
        cases.append(AgentCase("claude", path.stem, match.group(1), None))
    return cases


def run_codex(case: AgentCase) -> dict:
    cmd = [
        "codex", "exec",
        "-m", case.model,
        "--skip-git-repo-check", "--ephemeral", "--sandbox", "read-only",
        "--json",
    ]
    if case.effort:
        cmd += ["-c", f'model_reasoning_effort="{case.effort}"']
    cmd.append(PROMPT)
    started = time.monotonic()
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=120, cwd=str(BUNDLE_ROOT))
    elapsed_ms = round((time.monotonic() - started) * 1000)
    usage = {}
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.completed":
            usage = event.get("usage", {})
    return {
        "input_tokens": usage.get("input_tokens"),
        "cached_tokens": usage.get("cached_input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "reasoning_tokens": usage.get("reasoning_output_tokens"),
        "cost_usd": None,
        "elapsed_ms": elapsed_ms,
        "ok": proc.returncode == 0 and bool(usage),
        "stderr_tail": proc.stderr.strip().splitlines()[-1] if proc.returncode != 0 else "",
    }


def run_claude(case: AgentCase) -> dict:
    cmd = [
        "claude", "-p",
        "--model", case.model,
        "--output-format", "json",
        "--max-budget-usd", CLAUDE_BUDGET_USD,
        PROMPT,
    ]
    started = time.monotonic()
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=120, cwd=str(BUNDLE_ROOT))
    elapsed_ms = round((time.monotonic() - started) * 1000)
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        result = {}
    model_usage = next(iter(result.get("modelUsage", {}).values()), {})
    return {
        "input_tokens": model_usage.get("inputTokens"),
        "cached_tokens": model_usage.get("cacheReadInputTokens"),
        "output_tokens": model_usage.get("outputTokens"),
        "reasoning_tokens": None,
        "cost_usd": result.get("total_cost_usd"),
        "elapsed_ms": elapsed_ms,
        "ok": proc.returncode == 0 and bool(model_usage) and not result.get("is_error"),
        "stderr_tail": proc.stderr.strip().splitlines()[-1] if proc.returncode != 0 else "",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Actually call codex/claude (spends real API usage)")
    parser.add_argument("--only", choices=("codex", "claude"), help="Restrict to one platform")
    parser.add_argument("--agent", help="Restrict to one agent name (e.g. research)")
    args = parser.parse_args(argv)

    cases = []
    if args.only in (None, "codex"):
        cases += load_codex_agents()
    if args.only in (None, "claude"):
        cases += load_claude_agents()
    if args.agent:
        cases = [c for c in cases if c.name == args.agent]

    if not args.live:
        print(f"DRY RUN (pass --live to actually call the CLIs; each call spends real API usage)\n")
        for case in cases:
            print(f"  {case.platform:6s} {case.name:10s} model={case.model:20s} effort={case.effort}")
        return 0

    runner = {"codex": run_codex, "claude": run_claude}
    rows = []
    for case in cases:
        print(f"running {case.platform}/{case.name} ({case.model}, effort={case.effort})...", file=sys.stderr)
        result = runner[case.platform](case)
        rows.append((case, result))

    header = f"{'platform':8s} {'agent':10s} {'model':22s} {'effort':7s} {'in':>8s} {'cached':>8s} {'out':>6s} {'cost$':>8s} {'ms':>6s}  ok"
    print(header)
    print("-" * len(header))
    for case, result in rows:
        cost = f"{result['cost_usd']:.4f}" if result["cost_usd"] is not None else "n/a"
        print(
            f"{case.platform:8s} {case.name:10s} {case.model:22s} {str(case.effort):7s} "
            f"{str(result['input_tokens']):>8s} {str(result['cached_tokens']):>8s} {str(result['output_tokens']):>6s} "
            f"{cost:>8s} {result['elapsed_ms']:>6d}  {'yes' if result['ok'] else 'NO: ' + result['stderr_tail']}"
        )
    return 0 if all(r["ok"] for _, r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Measure real token usage per task-router agent (codex-task-router + claude-task-router).

Runs one minimal real call per agent and reports the token usage the CLI itself
reports, so you can confirm the intended model/effort is actually what gets
billed. Dry-run by default; costs real API usage with --live.

Codex caveat: the installed `codex` CLI has no flag to force-invoke a named
`[agents.*]` profile directly (`--agent` does not exist; agents are only
picked by Codex's own internal multi-agent delegator during a live session).
So the codex rows below verify "this model+effort combo is a real, billable
combination", not "config.toml agent registration actually routes to it" --
that half is not independently testable from outside a live session.

Claude does support real agent selection from the CLI (`--agent <name>` with
`--plugin-dir <dir>` to load an uninstalled plugin for one call), so the
claude rows here genuinely exercise agent registration + selection, not just
a raw --model call.
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
CLAUDE_PLUGIN_DIR = BUNDLE_ROOT / "plugins" / "claude-task-router"
CLAUDE_AGENTS_DIR = CLAUDE_PLUGIN_DIR / "agents"
CLAUDE_BUDGET_USD = "0.25"  # --plugin-dir re-caches the plugin's context on every call
CALL_TIMEOUT_SECONDS = 120


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


def timed_out_result(elapsed_ms: int) -> dict:
    return {
        "input_tokens": None,
        "cached_tokens": None,
        "output_tokens": None,
        "reasoning_tokens": None,
        "cost_usd": None,
        "elapsed_ms": elapsed_ms,
        "ok": False,
        "stderr_tail": f"timed out after {CALL_TIMEOUT_SECONDS}s",
    }


def run_codex(case: AgentCase) -> dict:
    """Verifies the model+effort combo is real and billable (see module docstring
    for why this cannot also verify config.toml agent selection)."""
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
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=CALL_TIMEOUT_SECONDS, cwd=str(BUNDLE_ROOT))
    except subprocess.TimeoutExpired:
        return timed_out_result(round((time.monotonic() - started) * 1000))
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
    """Loads claude-task-router as an uninstalled plugin and selects the named
    agent for real, so this exercises actual registration, not just --model."""
    cmd = [
        "claude", "-p",
        "--plugin-dir", str(CLAUDE_PLUGIN_DIR),
        "--agent", case.name,
        "--output-format", "json",
        "--max-budget-usd", CLAUDE_BUDGET_USD,
        PROMPT,
    ]
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=CALL_TIMEOUT_SECONDS, cwd=str(BUNDLE_ROOT))
    except subprocess.TimeoutExpired:
        return timed_out_result(round((time.monotonic() - started) * 1000))
    elapsed_ms = round((time.monotonic() - started) * 1000)
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        result = {}
    model_usage = next(iter(result.get("modelUsage", {}).values()), {})
    used_model = next(iter(result.get("modelUsage", {})), None)
    matches_expected = used_model is not None and case.model in used_model
    return {
        "input_tokens": model_usage.get("inputTokens"),
        "cached_tokens": model_usage.get("cacheReadInputTokens"),
        "output_tokens": model_usage.get("outputTokens"),
        "reasoning_tokens": None,
        "cost_usd": result.get("total_cost_usd"),
        "elapsed_ms": elapsed_ms,
        "ok": proc.returncode == 0 and bool(model_usage) and matches_expected,
        "stderr_tail": (proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "")
        or (f"used model {used_model!r}, expected {case.model!r}" if not matches_expected else ""),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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
        if not cases:
            print(f"no agent named {args.agent!r} found under --only={args.only or 'codex,claude'}", file=sys.stderr)
            return 2

    if not args.live:
        print("DRY RUN (pass --live to actually call the CLIs; each call spends real API usage)\n")
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

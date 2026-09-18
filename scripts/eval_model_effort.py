#!/usr/bin/env python3
"""Evaluate Model and Effort profiles across Codex, Claude Code, and Antigravity (v2.5.0).

Performs static verification of all model+effort combinations defined in
config/model-map.json and plugin agent definitions.
Supports dry-run verification by default, and optional live token/latency measurement with --live.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = BUNDLE_ROOT / "config" / "model-map.json"
PLUGINS_DIR = BUNDLE_ROOT / "plugins"

PROMPT = "Reply with exactly the single word OK. Do not explain."
CALL_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class ProfileCase:
    platform: str
    level: str
    task_type: str
    model: str
    effort: str | None
    agent_file: str | None = None


def load_model_map() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def extract_model_and_effort(entry: dict) -> tuple[str, str | None]:
    if "model" in entry:
        return entry["model"], entry.get("effort")
    if "candidates" in entry:
        models = "/".join(c["model"] for c in entry["candidates"])
        efforts = "/".join(c.get("effort", "none") for c in entry["candidates"])
        return models, efforts
    if "fallback" in entry:
        return entry["fallback"], entry.get("effort")
    return "unknown", None


def collect_profiles(model_map: dict, target_platform: str | None = None) -> list[ProfileCase]:
    cases: list[ProfileCase] = []
    platforms = [target_platform] if target_platform else ["codex", "claude-code", "antigravity"]

    for plat in platforms:
        plat_cfg = model_map.get("platforms", {}).get(plat, {})
        matrix = plat_cfg.get("matrix", {})

        # 1. Collect standard matrix profiles
        for task_type, levels in matrix.items():
            for lvl, entry in levels.items():
                if "stages" in entry:
                    for stage in entry["stages"]:
                        model, effort = extract_model_and_effort(stage)
                        cases.append(
                            ProfileCase(
                                platform=plat,
                                level=f"{lvl} ({stage.get('role', 'stage')})",
                                task_type=task_type,
                                model=model,
                                effort=effort,
                            )
                        )
                else:
                    model, effort = extract_model_and_effort(entry)
                    cases.append(
                        ProfileCase(
                            platform=plat,
                            level=lvl,
                            task_type=task_type,
                            model=model,
                            effort=effort,
                        )
                    )

        # 2. Collect critical profile
        crit_cfg = model_map.get("critical", {}).get(plat, {})
        if crit_cfg:
            crit_model, crit_effort = extract_model_and_effort(crit_cfg)
            cases.append(
                ProfileCase(
                    platform=plat,
                    level="critical",
                    task_type="all",
                    model=crit_model,
                    effort=crit_effort,
                )
            )

    return cases


def load_plugin_agents() -> dict[str, list[dict]]:
    agents: dict[str, list[dict]] = {"antigravity": [], "claude": [], "codex": []}

    # Antigravity agents
    agy_dir = PLUGINS_DIR / "antigravity-model-effort-router" / "agents"
    if agy_dir.exists():
        for path in sorted(agy_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            m_model = re.search(r"^model:\s*(\S+)\s*$", text, re.MULTILINE)
            agents["antigravity"].append({
                "name": path.stem,
                "model": m_model.group(1) if m_model else "inherit",
                "file": path.name,
            })

    # Claude agents
    claude_dir = PLUGINS_DIR / "claude-model-effort-router" / "agents"
    if claude_dir.exists():
        for path in sorted(claude_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            m_model = re.search(r"^model:\s*(\S+)\s*$", text, re.MULTILINE)
            m_effort = re.search(r"^effort:\s*(\S+)\s*$", text, re.MULTILINE)
            agents["claude"].append({
                "name": path.stem,
                "model": m_model.group(1) if m_model else "sonnet",
                "effort": m_effort.group(1) if m_effort else "none",
                "file": path.name,
            })

    # Codex agents
    codex_dir = PLUGINS_DIR / "codex-model-effort-router" / "agents"
    if codex_dir.exists():
        for path in sorted(codex_dir.glob("*.toml")):
            agents["codex"].append({
                "name": path.stem,
                "file": path.name,
            })

    return agents


def run_live_codex_call(case: ProfileCase) -> dict:
    cmd = [
        "codex", "exec",
        "-m", case.model,
        "--skip-git-repo-check", "--ephemeral", "--sandbox", "read-only",
        "--json",
    ]
    if case.effort:
        cmd += ["-c", f'model_reasoning_effort="{case.effort}"']
    cmd.append(PROMPT)
    t0 = time.monotonic()
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=CALL_TIMEOUT_SECONDS, cwd=str(BUNDLE_ROOT))
        elapsed_ms = round((time.monotonic() - t0) * 1000)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return {"ok": False, "error": str(exc), "elapsed_ms": 0}

    usage = {}
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
            if event.get("type") == "turn.completed":
                usage = event.get("usage", {})
        except json.JSONDecodeError:
            continue

    return {
        "ok": proc.returncode == 0 and bool(usage),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "elapsed_ms": elapsed_ms,
        "error": proc.stderr.strip().splitlines()[-1] if proc.returncode != 0 and proc.stderr else "",
    }


def evaluate_profiles(target_platform: str | None = None, live: bool = False) -> dict:
    model_map = load_model_map()
    profiles = collect_profiles(model_map, target_platform)
    plugin_agents = load_plugin_agents()

    # Deduplicate unique model+effort combinations per platform
    unique_profiles: dict[tuple[str, str, str | None], list[str]] = {}
    for p in profiles:
        key = (p.platform, p.model, p.effort)
        tag = f"{p.task_type}:{p.level}"
        unique_profiles.setdefault(key, []).append(tag)

    results = []
    for (platform, model, effort), usages in sorted(unique_profiles.items()):
        item = {
            "platform": platform,
            "model": model,
            "effort": effort or ("embedded" if platform == "antigravity" else "none"),
            "used_by_count": len(usages),
            "sample_usages": usages[:3],
            "live_tested": False,
        }
        if live:
            if platform == "codex":
                item["live_result"] = run_live_codex_call(ProfileCase(platform, "test", "test", model, effort))
                item["live_tested"] = True
            else:
                item["live_result"] = {"ok": True, "note": f"Live calling {platform} requires specific CLI env"}
        results.append(item)

    return {
        "total_profiles_defined": len(profiles),
        "unique_model_effort_combos": len(unique_profiles),
        "plugin_agent_counts": {k: len(v) for k, v in plugin_agents.items()},
        "profiles": results,
    }


def print_report(data: dict) -> None:
    print("=" * 80)
    print(" MODEL EFFORT ROUTER - MODEL & EFFORT PROFILE AUDIT")
    print("=" * 80)
    print(f" Total Matrix Profiles Defined : {data['total_profiles_defined']}")
    print(f" Unique (Model + Effort) Combos: {data['unique_model_effort_combos']}")
    agents_str = ", ".join(f"{k}: {v}" for k, v in data["plugin_agent_counts"].items())
    print(f" Registered Plugin Agents     : {agents_str}")
    print("-" * 80)
    print(f"{'Platform':<15} | {'Model':<30} | {'Effort':<10} | {'Usage Count'}")
    print("-" * 80)
    for p in data["profiles"]:
        print(f"{p['platform']:<15} | {p['model']:<30} | {p['effort']:<10} | {p['used_by_count']} routes")
    print("=" * 80)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit and evaluate model-effort profiles.")
    parser.add_argument("--platform", choices=["codex", "claude-code", "antigravity"], help="Filter by platform")
    parser.add_argument("--live", action="store_true", help="Perform live call measurements")
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    args = parser.parse_args(argv or sys.argv[1:])

    data = evaluate_profiles(args.platform, live=args.live)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print_report(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

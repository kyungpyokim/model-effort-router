"""Role/effort (+ optional tier) evaluation helpers. Frozen L1-L5 corpora are not scored here.

  python3 -m evaluation.compare CORPUS --backend jev [--backend nimble ...] [--json OUT.json] [--timeout 30]

Makes live backend calls; the Jev key comes from user config (jev.api_key) or TYPESAFE_API_KEY.
"""

import argparse
import json
import os
import sys

import statistics
import time

from model_effort_router.difficulty.chain import classify_with_fallback
from model_effort_router.difficulty.decision import DifficultyInput


def evaluate_backend(name, backend, rows, *, clock=time.monotonic, timeout_s=30):
    scored = [
        row
        for row in rows
        if isinstance(row.get("final"), dict)
        and row["final"].get("role") is not None
        and row["final"].get("effort") is not None
    ]
    result = {
        "backend": name,
        "n": len(scored),
        "role_exact": 0,
        "effort_exact": 0,
        "joint_exact": 0,
        "tier_n": sum(row["final"].get("tier") is not None for row in scored),
        "tier_exact": 0,
        "fallback_count": 0,
        "errors": [],
        "predictions": [],
        "tokens": None,
    }
    latencies = []
    for row in scored:
        task = DifficultyInput(row["task"], tuple(row.get("paths", ())))
        started = clock()
        try:
            decision, causes = classify_with_fallback(task, [backend], timeout_s)
            result["fallback_count"] += bool(causes) or decision.backend != getattr(backend, "name", name)
            role_ok = decision.role == row["final"]["role"]
            effort_ok = decision.effort == row["final"]["effort"]
            result["role_exact"] += role_ok
            result["effort_exact"] += effort_ok
            result["joint_exact"] += role_ok and effort_ok
            if row["final"].get("tier") is not None:
                result["tier_exact"] += decision.tier == row["final"]["tier"]
            result["predictions"].append(
                {"id": row["id"], "role": decision.role, "effort": decision.effort, "tier": decision.tier}
            )
        except Exception as exc:
            result["fallback_count"] += 1
            result["errors"].append({"id": row.get("id"), "type": type(exc).__name__})
        latencies.append((clock() - started) * 1000)
    result["latency_ms"] = {"p50": statistics.median(latencies), "max": max(latencies)} if latencies else None
    return result


def compare(rows, backends, **kwargs):
    rows = [r for r in rows if r.get("status") == "adjudicated"]
    return {
        "cases": len(rows),
        "metric": "role_effort",
        "backends": {name: evaluate_backend(name, backend, rows, **kwargs) for name, backend in backends.items()},
    }


def to_markdown(result):
    show_tier = any(item.get("tier_n", 0) for item in result["backends"].values())
    title = "Role / effort / tier" if show_tier else "Role / effort"
    labels = "role, effort and tier labels" if show_tier else "role and effort labels"
    lines = [
        f"# {title} comparison ({result['cases']} adjudicated cases)",
        "",
        f"Historical L1-L5 corpora are excluded; this report scores only explicit {labels}.",
        "",
        "| Provider | Cases | Role exact | Effort exact | Joint exact | "
        + ("Tier exact | " if show_tier else "")
        + "Provider failures |",
        "|---|---:|---:|---:|---:|" + ("---:|" if show_tier else "") + "---:|",
    ]
    for name, item in result["backends"].items():
        n = item["n"]

        def pct(key):
            return f"{item[key]}/{n} ({item[key] / n:.0%})" if n else "-"

        tn = item.get("tier_n", 0)
        tier = f" {item['tier_exact']}/{tn} ({item['tier_exact'] / tn:.0%}) |" if tn else " - |"
        lines.append(
            f"| {name} | {n} | {pct('role_exact')} | {pct('effort_exact')} | {pct('joint_exact')} |"
            + (tier if show_tier else "")
            + f" {item['fallback_count']} |"
        )
    return "\n".join(lines) + "\n"


def build_backend(name, repo_config=None, user_config=None):
    """Backend from the registry, configured like policy.router._make_backends (resolved repo/user config)."""
    from model_effort_router.difficulty.registry import BACKENDS, create
    from model_effort_router.policy.config import resolve_config

    if name not in BACKENDS:
        raise ValueError(f"unknown backend {name!r}; valid: {', '.join(sorted(BACKENDS))}")
    cfg = resolve_config(repo=repo_config, user=user_config)
    options = {}
    if name in ("nimble", "laya"):
        backend_options = getattr(cfg, name, None)
        if backend_options:
            options["options"] = backend_options
    if name == "jev" and user_config:
        jev = user_config.get("jev") or {}
        options["api_key"] = jev.get("api_key")
        if jev.get("model"):
            options["model"] = jev["model"]
    if name == "openai_decisions" and user_config:
        options["api_key"] = (user_config.get("openai") or {}).get("api_key")
    return create(name, **options)


def _failed_backends(result):
    for name, item in result["backends"].items():
        if item["n"] and item["fallback_count"] == item["n"]:
            kinds = sorted({e["type"] for e in item["errors"]}) or ["fallback"]
            yield name, kinds


def main(argv=None, *, backend_factory=None):
    from evaluation import cases
    from model_effort_router.host.codex_hooks import load_configs

    parser = argparse.ArgumentParser(prog="python3 -m evaluation.compare", description=__doc__.split("\n")[0])
    parser.add_argument("corpus")
    parser.add_argument("--backend", action="append", required=True, dest="backends")
    parser.add_argument("--json", dest="json_out")
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args(argv)
    out_file = None
    try:
        rows = cases.load(args.corpus)
        repo_config, user_config = load_configs(os.getcwd(), os.environ)
        for label, config in (("repo", repo_config), ("user", user_config)):
            if config is not None and not isinstance(config, dict):
                raise ValueError(f"{label} config must be a JSON object")
        factory = backend_factory or build_backend
        backends = {name: factory(name, repo_config, user_config) for name in args.backends}
        if args.json_out:  # fail before any paid call
            out_file = open(args.json_out, "w", encoding="utf-8")
    except (cases.CorpusError, OSError, KeyError, ValueError) as exc:
        print(f"compare: {exc}", file=sys.stderr)
        return 1
    try:
        result = compare(rows, backends, timeout_s=args.timeout)
        print(to_markdown(result), end="")
        if out_file:
            json.dump(result, out_file, ensure_ascii=False, indent=2)
    finally:
        if out_file:
            out_file.close()
    failed = list(_failed_backends(result))
    for name, kinds in failed:
        print(
            f"compare: backend {name!r} failed on every case ({', '.join(kinds)}); is its API key or endpoint configured?",
            file=sys.stderr,
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

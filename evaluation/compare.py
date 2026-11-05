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
    lines = [
        f"# Role / effort comparison ({result['cases']} adjudicated cases)",
        "",
        "Historical L1-L5 corpora are excluded; this report scores only explicit role and effort labels (plus tier where labeled).",
        "",
        "| Provider | Cases | Role exact | Effort exact | Joint exact | Tier exact | Provider failures |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, item in result["backends"].items():
        n = item["n"]

        def pct(key):
            return f"{item[key]}/{n} ({item[key] / n:.0%})" if n else "-"

        tn = item.get("tier_n", 0)
        tier = f"{item['tier_exact']}/{tn} ({item['tier_exact'] / tn:.0%})" if tn else "-"
        lines.append(
            f"| {name} | {n} | {pct('role_exact')} | {pct('effort_exact')} | {pct('joint_exact')} | {tier} | {item['fallback_count']} |"
        )
    return "\n".join(lines) + "\n"


def build_backend(name, user_config=None):
    """Backend from the registry; Jev/OpenAI keys come from user config like policy.router._make_backends."""
    from model_effort_router.difficulty.registry import create

    options = {}
    user_config = user_config or {}
    if name == "jev":
        jev = user_config.get("jev") or {}
        options["api_key"] = jev.get("api_key")
        if jev.get("model"):
            options["model"] = jev["model"]
    elif name == "openai_decisions":
        options["api_key"] = (user_config.get("openai") or {}).get("api_key")
    return create(name, **options)


def main(argv=None, *, backend_factory=None):
    from evaluation import cases
    from model_effort_router.host.codex_hooks import load_configs

    parser = argparse.ArgumentParser(prog="python3 -m evaluation.compare", description=__doc__.split("\n")[0])
    parser.add_argument("corpus")
    parser.add_argument("--backend", action="append", required=True, dest="backends")
    parser.add_argument("--json", dest="json_out")
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args(argv)
    try:
        rows = cases.load(args.corpus)
        user_config = load_configs(os.getcwd(), os.environ)[1]
        factory = backend_factory or build_backend
        backends = {name: factory(name, user_config) for name in args.backends}
    except (cases.CorpusError, OSError, KeyError, ValueError) as exc:
        print(f"compare: {exc}", file=sys.stderr)
        return 1
    result = compare(rows, backends, timeout_s=args.timeout)
    print(to_markdown(result), end="")
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())

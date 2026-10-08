"""Role/effort evaluation helpers. Frozen L1-L5 corpora are not scored here."""

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
            result["predictions"].append({"id": row["id"], "role": decision.role, "effort": decision.effort})
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
        "Historical L1-L5 corpora are excluded; this report scores only explicit role and effort labels.",
        "",
        "| Provider | Cases | Role exact | Effort exact | Joint exact | Provider failures |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, item in result["backends"].items():
        n = item["n"]

        def pct(key):
            return f"{item[key]}/{n} ({item[key] / n:.0%})" if n else "-"

        lines.append(
            f"| {name} | {n} | {pct('role_exact')} | {pct('effort_exact')} | {pct('joint_exact')} | {item['fallback_count']} |"
        )
    return "\n".join(lines) + "\n"

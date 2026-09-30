"""Backend comparison over adjudicated corpus cases (spec 22.2).

Lives in the top-level `evaluation/` package, not in `model_effort_router/`: evaluation tooling is
dev-only and must not be copied into the shipped plugin bundle (scripts/sync_plugin.py bundles only the core).

Usage: python3 -m evaluation.compare --corpus FILE --backends a,b [--json OUT] [--md OUT] [--dry-run] [--live]
`subscription` calls a model (`codex exec`), so it only runs with --live.
"""
import argparse
import json
import statistics
import sys
import time

from model_effort_router.difficulty.chain import classify_with_fallback
from model_effort_router.difficulty.decision import LEVELS, DifficultyDecision, DifficultyInput
from model_effort_router.difficulty.registry import BACKENDS, create
from model_effort_router.difficulty.risk import detect_risk_flags
from model_effort_router.policy.stages import decide_stages, restrict_to_target
from model_effort_router.policy.targeting import classify_target

from . import cases as corpus

LIVE_BACKENDS = {"subscription"}  # backends that call a model
CRITICAL_MAX_PREDICTED = LEVELS.index("L2")
TIMEOUT_S = 30.0


def _is_critical(final):
    return final["level"] in ("L4", "L5") or bool(final["risk_flags"])


def _profiles(decision, target):
    policy = restrict_to_target(decide_stages(decision), target)
    return tuple((s.stage, s.tier, s.effort) for s in policy.stages)


def _add_usage(total, usage):
    if not usage:
        return total
    total = total or {"input": 0, "output": 0}
    return {"input": total["input"] + usage.get("input_tokens", 0),
            "output": total["output"] + usage.get("output_tokens", 0)}


def evaluate_backend(name, backend, rows, *, clock=time.monotonic, timeout_s=TIMEOUT_S):
    scored = [r for r in corpus.adjudicated(rows) if r["final"]["level"] is not None]
    m = {"backend": name, "n": len(scored), "exact": 0, "within_one": 0, "over": 0, "under": 0,
         "critical_total": 0, "critical_miss": 0, "fallback_count": 0, "stage_profile_match": 0,
         "tokens": None, "misses": [], "skipped_no_route": len(corpus.adjudicated(rows)) - len(scored)}
    distance, latencies = 0, []
    for r in scored:
        final = r["final"]
        task = DifficultyInput(task=r["task"], paths=tuple(r["paths"]))
        if hasattr(backend, "last_usage"):
            backend.last_usage = None  # never count a previous call's usage
        t0 = clock()
        decision = classify_with_fallback(task, [backend], timeout_s)
        latencies.append((clock() - t0) * 1000)
        if decision.backend != getattr(backend, "name", name):
            m["fallback_count"] += 1
        m["tokens"] = _add_usage(m["tokens"], getattr(backend, "last_usage", None))  # failed calls cost too
        diff = LEVELS.index(decision.level) - LEVELS.index(final["level"])
        distance += abs(diff)
        m["exact"] += diff == 0
        m["within_one"] += abs(diff) <= 1
        m["over"] += diff > 0
        m["under"] += diff < 0
        if diff:
            m["misses"].append({"id": r["id"], "final": final["level"], "predicted": decision.level})
        if _is_critical(final):
            m["critical_total"] += 1
            m["critical_miss"] += LEVELS.index(decision.level) <= CRITICAL_MAX_PREDICTED
        # routing level: same pipeline as router.route() -> detected flags merged -> Stage Policy
        predicted = decision.with_risk_flags(detect_risk_flags(r["task"], r["paths"]))
        expected = DifficultyDecision(final["level"], "label", risk_flags=tuple(final["risk_flags"]))
        m["stage_profile_match"] += _profiles(predicted, final["target"]) == _profiles(expected, final["target"])
    m["mean_distance"] = distance / len(scored) if scored else 0.0
    m["latency_ms"] = ({"p50": statistics.median(latencies), "max": max(latencies)} if latencies else None)
    return m


def target_accuracy(rows):
    """Backend-independent: does the cheap rule-based target classifier agree with the final target?"""
    adj = corpus.adjudicated(rows)
    return {"n": len(adj), "correct": sum(classify_target(r["task"], r["paths"]) == r["final"]["target"] for r in adj)}


def compare(rows, backends, **kw):
    return {"cases": len(corpus.adjudicated(rows)), "target_accuracy": target_accuracy(rows),
            "backends": {name: evaluate_backend(name, b, rows, **kw) for name, b in backends.items()}}


def _pct(part, whole):
    return f"{part}/{whole} ({part / whole:.0%})" if whole else "-"


def to_markdown(res):
    t = res["target_accuracy"]
    lines = [f"# Backend comparison ({res['cases']} adjudicated cases)", "",
             f"Target rules accuracy: {_pct(t['correct'], t['n'])}", "",
             "| backend | n | exact | +-1 | over | under | mean dist | critical miss | p50 ms | max ms | "
             "tokens in/out | fallback | stage profiles |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, m in res["backends"].items():
        lat = m["latency_ms"] or {}
        tok = m["tokens"]
        lines.append("| {} | {} | {} | {} | {} | {} | {:.2f} | {} | {} | {} | {} | {} | {} |".format(
            name, m["n"], _pct(m["exact"], m["n"]), _pct(m["within_one"], m["n"]), m["over"], m["under"],
            m["mean_distance"], _pct(m["critical_miss"], m["critical_total"]),
            f"{lat['p50']:.0f}" if lat else "-", f"{lat['max']:.0f}" if lat else "-",
            f"{tok['input']}/{tok['output']}" if tok else "n/a", m["fallback_count"],
            _pct(m["stage_profile_match"], m["n"])))
    lines += ["", "Critical miss = final L4/L5 or any risk flag, predicted <= L2. Fallback cases are scored as the "
              "default L3 decision. TODO(Phase 6): confidence calibration, cost and local resource usage."]
    return "\n".join(lines) + "\n"


def main(argv=None, registry=None):
    registry = BACKENDS if registry is None else registry
    ap = argparse.ArgumentParser(prog="evaluation.compare", description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--backends", required=True, help="comma separated registry names")
    ap.add_argument("--json")
    ap.add_argument("--md")
    ap.add_argument("--dry-run", action="store_true", help="validate and print the plan; call no backend")
    ap.add_argument("--live", action="store_true",
                    help=f"allow model-calling backends {sorted(LIVE_BACKENDS)}; consumes subscription usage")
    args = ap.parse_args(argv)
    names = [n for n in args.backends.split(",") if n]
    unknown = [n for n in names if n not in registry]
    if unknown:
        print(f"unknown backend(s): {unknown}; registered: {sorted(registry)}", file=sys.stderr)
        return 2
    blocked = [n for n in names if n in LIVE_BACKENDS and not args.live and not args.dry_run]
    if blocked:
        print(f"refusing to run {blocked} without --live (it calls a model and consumes subscription usage)",
              file=sys.stderr)
        return 2
    try:
        rows = corpus.load(args.corpus)
    except (corpus.CorpusError, OSError) as exc:
        print(f"invalid corpus: {exc}", file=sys.stderr)
        return 1
    adj = corpus.adjudicated(rows)
    if not adj:
        print("no adjudicated cases in corpus; label and adjudicate first (docs/evaluation/labeling-guide.md)",
              file=sys.stderr)
        return 1
    if args.dry_run:
        print(f"dry-run: would run {names} over {len(adj)} adjudicated cases "
              f"({sum(r['final']['level'] is not None for r in adj)} scored); no backend called")
        return 0
    res = compare(rows, {n: create(n, registry) for n in names})
    md = to_markdown(res)
    for path, text in ((args.json, json.dumps(res, ensure_ascii=False, indent=2)), (args.md, md)):
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())

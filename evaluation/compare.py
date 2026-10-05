"""Backend comparison over adjudicated corpus cases (spec 22.2).

Lives in the top-level `evaluation/` package, not in `model_effort_router/`: evaluation tooling is
dev-only and must not be copied into the shipped plugin bundle (scripts/sync_plugin.py bundles only the core).

Usage: python3 -m evaluation.compare --corpus FILE --backends a,b [--json OUT] [--md OUT] [--dry-run] [--live]
`subscription` calls a model (`codex exec`), so it only runs with --live. `nimble` and `nimble_jev` use the `difficulty.nimble` options
of the working directory's .model-effort-router.json (or the user config), exactly as mer does.
"""
import argparse
import json
import os
import statistics
import sys
import time

from model_effort_router.difficulty.chain import classify_with_fallback
from model_effort_router.difficulty.decision import LEVELS, DifficultyDecision, DifficultyInput
from model_effort_router.difficulty.registry import BACKENDS, create
from model_effort_router.difficulty.conditional import NimbleJevBackend
from model_effort_router.difficulty.nimble import NimbleBackend
from model_effort_router.difficulty.risk import detect_risk_flags
from model_effort_router.host.codex_hooks import load_configs
from model_effort_router.policy.config import resolve_config
from model_effort_router.policy.session import REVIEW_DEFAULT, session_plan
from model_effort_router.policy.targeting import classify_target

from . import cases as corpus

LIVE_BACKENDS = {"subscription", "jev", "nimble", "nimble_jev"}  # backends that call a model
CRITICAL_MAX_PREDICTED = LEVELS.index("L2")
TIMEOUT_S = 30.0


def _is_critical(final):
    return final["level"] in ("L4", "L5") or bool(final["risk_flags"])


def _profiles(decision, target):
    """What a mer run would do: the profile that runs for plan_only / review_only, else start, ladder, plan-first, review."""
    sp = session_plan(decision)
    if target == "plan_only":
        return sp.plan_profile
    return (sp.review or REVIEW_DEFAULT) if target == "review_only" else (sp.start, sp.ladder, sp.plan_first, sp.review)


def _count(acc, predicted, gold):
    p, g = set(predicted), set(gold)
    return {"tp": acc["tp"] + len(p & g), "fp": acc["fp"] + len(p - g), "fn": acc["fn"] + len(g - p)}


def _zero():
    return {"tp": 0, "fp": 0, "fn": 0}


def _add_usage(total, usage):
    if not usage:
        return total
    total = total or {"input": 0, "output": 0}
    return {"input": total["input"] + usage.get("input_tokens", 0),
            "output": total["output"] + usage.get("output_tokens", 0)}


def evaluate_backend(name, backend, rows, *, clock=time.monotonic, timeout_s=TIMEOUT_S):
    """Runs the backend on EVERY adjudicated case (the target is scored on all, level and risk only where a level exists)."""
    adj = corpus.adjudicated(rows)
    scored = [r for r in adj if r["final"]["level"] is not None]
    m = {"backend": name, "n": len(scored), "exact": 0, "within_one": 0, "over": 0, "under": 0,
         "critical_total": 0, "critical_miss": 0, "fallback_count": 0, "stage_profile_match": 0,
         "target_n": len(adj), "target_correct": 0, "target_from_backend": 0,
         "tokens": None, "misses": [], "skipped_no_route": len(adj) - len(scored),
         "risk": {"backend": _zero(), "merged": _zero()}, "predictions": []}
    distance, latencies = 0, []
    for r in adj:
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
        # the target the router would use: the backend's own, else the rules (as router.route() does)
        target = decision.target or classify_target(r["task"], r["paths"])
        m["target_correct"] += target == final["target"]
        m["target_from_backend"] += decision.target is not None
        pred = {"id": r["id"], "level": decision.level, "risk_flags": list(decision.risk_flags), "target": target,
                "target_source": "backend" if decision.target else "rules"}
        scores = getattr(backend, "last_risk_scores", None)
        if scores is not None:
            pred["risk_scores"] = dict(scores)  # raw per-flag scores, for threshold calibration
        if decision.distribution and decision.backend == getattr(backend, "name", name):
            pred["distribution"] = dict(decision.distribution)  # level probabilities, for level-rule calibration
        m["predictions"].append(pred)
        if final["level"] is None:
            continue
        diff = LEVELS.index(decision.level) - LEVELS.index(final["level"])
        distance += abs(diff)
        m["exact"] += diff == 0
        m["within_one"] += abs(diff) <= 1
        m["over"] += diff > 0
        m["under"] += diff < 0
        if diff:
            m["misses"].append({"id": r["id"], "final": final["level"], "predicted": decision.level})
        if _is_critical(final):  # a miss = judged lower than labeled AND at L2 or below (a right L2 is no miss)
            m["critical_total"] += 1
            m["critical_miss"] += diff < 0 and LEVELS.index(decision.level) <= CRITICAL_MAX_PREDICTED
        # routing level: same pipeline as router.route() -> detected flags merged -> session_plan
        predicted = decision.with_risk_flags(detect_risk_flags(r["task"], r["paths"]))
        m["risk"] = {"backend": _count(m["risk"]["backend"], decision.risk_flags, final["risk_flags"]),
                     "merged": _count(m["risk"]["merged"], predicted.risk_flags, final["risk_flags"])}
        expected = DifficultyDecision(final["level"], "label", risk_flags=tuple(final["risk_flags"]))
        m["stage_profile_match"] += _profiles(predicted, final["target"]) == _profiles(expected, final["target"])
    m["mean_distance"] = distance / len(scored) if scored else 0.0
    m["latency_ms"] = ({"p50": statistics.median(latencies), "max": max(latencies)} if latencies else None)
    return m


def regex_risk(rows):
    """Backend-independent: the rule-based detector alone (it is merged into every backend's flags)."""
    acc = _zero()
    for r in corpus.adjudicated(rows):
        if r["final"]["level"] is not None:
            acc = _count(acc, detect_risk_flags(r["task"], r["paths"]), r["final"]["risk_flags"])
    return acc


def target_accuracy(rows):
    """Backend-independent: does the rule-based target classifier agree with the final target? With the case paths,
    and text-only (what the hook sees: it has no paths)."""
    adj = corpus.adjudicated(rows)
    return {"n": len(adj), "correct": sum(classify_target(r["task"], r["paths"]) == r["final"]["target"] for r in adj),
            "text_only_correct": sum(classify_target(r["task"], ()) == r["final"]["target"] for r in adj)}


def compare(rows, backends, **kw):
    return {"cases": len(corpus.adjudicated(rows)), "target_accuracy": target_accuracy(rows), "regex_risk": regex_risk(rows),
            "backends": {name: evaluate_backend(name, b, rows, **kw) for name, b in backends.items()}}


def _pct(part, whole):
    return f"{part}/{whole} ({part / whole:.0%})" if whole else "-"


def _pr(c):
    """'recall / precision' of risk flags."""
    rec = _pct(c["tp"], c["tp"] + c["fn"])
    return f"{rec} / {_pct(c['tp'], c['tp'] + c['fp'])}"


def to_markdown(res):
    t = res["target_accuracy"]
    lines = [f"# Backend comparison ({res['cases']} adjudicated cases)", "",
             f"Target rules accuracy: with paths {_pct(t['correct'], t['n'])}; text-only (what the hook sees) "
             f"{_pct(t['text_only_correct'], t['n'])}",
             f"Rule-based risk flags alone (recall / precision): {_pr(res['regex_risk'])}", "",
             "| backend | n | target (backend) | exact | +-1 | over | under | mean dist | critical miss | p50 ms | max ms | "
             "tokens in/out | fallback | session profiles | risk backend (rec / prec) | risk merged (rec / prec) |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, m in res["backends"].items():
        lat = m["latency_ms"] or {}
        tok = m["tokens"]
        lines.append("| {} | {} | {} | {} | {} | {} | {} | {:.2f} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
            name, m["n"], _pct(m["target_correct"], m["target_n"]), _pct(m["exact"], m["n"]), _pct(m["within_one"], m["n"]), m["over"], m["under"],
            m["mean_distance"], _pct(m["critical_miss"], m["critical_total"]),
            f"{lat['p50']:.0f}" if lat else "-", f"{lat['max']:.0f}" if lat else "-",
            f"{tok['input']}/{tok['output']}" if tok else "n/a", m["fallback_count"],
            _pct(m["stage_profile_match"], m["n"]), _pr(m["risk"]["backend"]), _pr(m["risk"]["merged"])))
    lines += ["", "Critical miss = final L4/L5 or any risk flag, predicted lower than labeled and <= L2. Fallback cases are scored as the "
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
                    help=f"allow model-calling backends {sorted(LIVE_BACKENDS)}; consumes subscription usage or external API credit")
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
              f"({sum(r['final']['level'] is not None for r in adj)} scored for level; every case is classified for the target); "
              "no backend called")
        return 0
    try:  # nimble gets the `difficulty.nimble` options mer would use from the cwd's repo/user config (thresholds, model, url)
        repo_cfg, user_cfg = load_configs(os.getcwd(), os.environ) if {"nimble", "nimble_jev"} & set(names) else (None, None)
        nimble_options = resolve_config(repo=repo_cfg, user=user_cfg).nimble
    except (ValueError, OSError) as exc:
        print(f"invalid router config: {exc}", file=sys.stderr)
        return 2
    real = {"nimble": NimbleBackend, "nimble_jev": NimbleJevBackend}  # only the real classes receive the options

    def opts(n):
        return {"options": nimble_options} if n in real and nimble_options and registry.get(n) is real[n] else {}
    res = compare(rows, {n: create(n, registry, **opts(n)) for n in names})
    md = to_markdown(res)
    for path, text in ((args.json, json.dumps(res, ensure_ascii=False, indent=2)), (args.md, md)):
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())

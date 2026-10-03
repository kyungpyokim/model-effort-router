"""Run records and Baseline-vs-Router comparison (spec 22.3).

Record: {case_id, run (1 if absent), mode: baseline|router, gate_overall, review_verdict, fix_rounds, requirements_met,
         usage: evaluation.usage.aggregate() output, wall_s}. `requirements_met` is set by hand (`mark`).
Decision rule (22.3): the router must keep quality AND cut total usage, otherwise the default mode must not be auto.
Usage: python3 -m evaluation.baseline report RUNS.jsonl [--json OUT] [--md OUT]
       python3 -m evaluation.baseline mark RUNS.jsonl CASE_ID MODE yes|no [--run K]
"""
import argparse
import json
import sys

MODES = ("baseline", "router")
GATES = ("passed", "failed", "incomplete")
VERDICTS = ("approved", "changes_requested", "unknown")  # unknown: review output had no parseable verdict
AUTO_OK, NOT_AUTO, INSUFFICIENT = "auto_allowed", "do_not_default_to_auto", "insufficient_data"


def validate_record(row):
    def fail(field, why):
        raise ValueError(f"record {row.get('case_id') if isinstance(row, dict) else row!r}: {field} {why}")

    if not isinstance(row, dict):
        fail("record", "must be an object")
    if not (isinstance(row.get("case_id"), str) and row["case_id"].strip()):
        fail("case_id", "must be a non-empty string")
    if row.get("mode") not in MODES:
        fail("mode", f"must be one of {MODES}")
    if row.get("gate_overall") not in (*GATES, None):
        fail("gate_overall", f"must be one of {GATES} or null")
    if row.get("review_verdict") not in (*VERDICTS, None):
        fail("review_verdict", f"must be one of {VERDICTS} or null")
    fix = row.get("fix_rounds", 0)
    if not (isinstance(fix, int) and not isinstance(fix, bool) and fix >= 0):
        fail("fix_rounds", "must be an integer >= 0")
    if row.get("requirements_met") not in (True, False, None):
        fail("requirements_met", "must be true, false or null (unjudged)")
    wall = row.get("wall_s")
    if not (isinstance(wall, (int, float)) and not isinstance(wall, bool) and wall >= 0):
        fail("wall_s", "must be a number >= 0")
    if row.get("router_active") not in (True, False, None):
        fail("router_active", "must be a boolean")
    if row.get("contaminated") not in (True, False, None):
        fail("contaminated", "must be a boolean")
    findings = row.get("review_findings")
    if findings is not None and not (isinstance(findings, int) and not isinstance(findings, bool) and findings >= 0):
        fail("review_findings", "must be an integer >= 0 or null")
    usage = row.get("usage")
    if not (isinstance(usage, dict) and isinstance(usage.get("total"), int)):
        fail("usage", "must be an object with an integer total (evaluation.usage.aggregate)")
    run = row.get("run", 1)  # records from before --repeat have no run: run 1
    if not (isinstance(run, int) and not isinstance(run, bool) and run >= 1):
        fail("run", "must be an integer >= 1")
    return {**row, "fix_rounds": fix, "run": run}


def load_records(path):
    with open(path, encoding="utf-8") as f:
        return [validate_record(json.loads(line)) for line in f if line.strip()]


def save_records(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def _signals(r):
    """Quality signals that are known (True = good). Unknown ones (None) are never compared."""
    return {"requirements": r["requirements_met"],
            "gate": None if r["gate_overall"] is None else r["gate_overall"] == "passed",
            "review": None if r["review_verdict"] is None else r["review_verdict"] == "approved"}


def incomplete_reasons(r):
    """Why this run's usage/outcome cannot be trusted (empty = complete)."""
    u, why = r["usage"], list(r["usage"].get("incomplete_reasons") or [])
    if r.get("error"):
        why.append("run_error")
    why += [f"no_usage:{s}" for s in u.get("stages_without_usage") or []]
    if r["mode"] == "router" and not u.get("total"):  # mer sessions leave rollouts; none found = nothing measured
        why.append("no_usage_measured")
    return why


def compare_pair(base, router):
    bs, rs = _signals(base), _signals(router)
    shared = [k for k in bs if bs[k] is not None and rs[k] is not None]
    worse = any(rs[k] < bs[k] for k in shared)
    better = any(rs[k] > bs[k] for k in shared)
    quality = "unknown" if not shared else "regressed" if worse else "improved" if better else "preserved"
    b, r = base["usage"]["total"], router["usage"]["total"]
    return {"case_id": base["case_id"], "run": base.get("run", 1), "quality": quality, "usage_delta": r - b,
            "usage_delta_pct": (r - b) / b * 100 if b else None,
            "time_delta_s": round(router["wall_s"] - base["wall_s"], 3),
            "fix_delta": router["fix_rounds"] - base["fix_rounds"],
            "baseline_total": b, "router_total": r, "router_findings": router.get("review_findings"),
            "incomplete": incomplete_reasons(base) + incomplete_reasons(router),
            "requirements_judged": base["requirements_met"] is not None and router["requirements_met"] is not None}


def _decide(pairs, agg):
    if not pairs:
        return INSUFFICIENT, "no case has both a baseline and a router run"
    if any(p["incomplete"] for p in pairs):
        return INSUFFICIENT, "usage or outcome incomplete for some runs (" + \
            "; ".join(f"{p['case_id']}: {','.join(p['incomplete'])}" for p in pairs if p["incomplete"]) + ")"
    if not all(p["requirements_judged"] for p in pairs):
        return INSUFFICIENT, "requirements_met is unset for some runs; set it with `mark`"
    if agg["quality"]["regressed"]:
        return NOT_AUTO, "router regressed quality on at least one case"
    if agg["usage"]["delta"] >= 0:
        return NOT_AUTO, "router did not reduce total usage (main session + classifier + subagents)"
    if agg["excluded"]:
        kinds = sorted({e["reason"] for e in agg["excluded"]})
        return INSUFFICIENT, f"runs were excluded ({', '.join(kinds)}); fix them before trusting a pass"
    return AUTO_OK, "quality kept and total usage reduced"


def _tag(run):
    return {} if run == 1 else {"run": run}  # run 1 stays untagged: output identical to single-run reports


def _case_means(pairs):
    """Per-case means over that case's runs (usage means; quality counts)."""
    out = []
    for case_id in dict.fromkeys(p["case_id"] for p in pairs):
        ps = [p for p in pairs if p["case_id"] == case_id]
        b, r = (sum(p[k] for p in ps) / len(ps) for k in ("baseline_total", "router_total"))
        out.append({"case_id": case_id, "runs": len(ps), "baseline_mean": b, "router_mean": r, "usage_delta_mean": r - b,
                    "usage_delta_pct": (r - b) / b * 100 if b else None,
                    "quality": {q: sum(p["quality"] == q for p in ps) for q in ("preserved", "improved", "regressed", "unknown")}})
    return out


def report(records):
    by = {}  # (case_id, run) -> {mode: record}
    for r in map(validate_record, records):
        if r["mode"] in by.setdefault((r["case_id"], r["run"]), {}):
            raise ValueError(f"duplicate {r['mode']} run for case {r['case_id']!r} (run {r['run']})")
        by[(r["case_id"], r["run"])][r["mode"]] = r
    excluded, usable = [], {}
    for (case_id, run), m in by.items():  # a router run that never routed (or a baseline that did) proves nothing
        if "router" in m and not m["router"].get("error") and m["router"].get("router_active") is not True:
            excluded.append({"case_id": case_id, **_tag(run), "reason": "router_inactive"})
        elif m.get("baseline", {}).get("contaminated"):
            excluded.append({"case_id": case_id, **_tag(run), "reason": "baseline_contaminated"})
        else:
            usable[(case_id, run)] = m
    by = usable
    pairs = [compare_pair(m["baseline"], m["router"]) for m in by.values() if len(m) == 2]
    b_tot, r_tot = sum(p["baseline_total"] for p in pairs), sum(p["router_total"] for p in pairs)
    agg = {"pairs": len(pairs), "unpaired": [c if run == 1 else f"{c}#r{run}" for (c, run), m in by.items() if len(m) < 2],
           "quality": {q: sum(p["quality"] == q for p in pairs) for q in ("preserved", "improved", "regressed", "unknown")},
           "usage": {"baseline": b_tot, "router": r_tot, "delta": r_tot - b_tot},
           "time_delta_s": round(sum(p["time_delta_s"] for p in pairs), 3),
           "fix_delta": sum(p["fix_delta"] for p in pairs),
           "excluded": excluded,
           "review_findings": sum(p["router_findings"] or 0 for p in pairs)}
    verdict, why = _decide(pairs, agg)
    return {"per_case": pairs, "per_case_mean": _case_means(pairs), "aggregate": agg,
            "decision": {"verdict": verdict, "reason": why}}


def to_markdown(rep):
    a, d = rep["aggregate"], rep["decision"]
    lines = [f"# Baseline vs Router ({a['pairs']} paired cases)", "", f"Decision: **{d['verdict']}** - {d['reason']}", "",
             f"Total usage: baseline {a['usage']['baseline']}, router {a['usage']['router']} "
             f"(delta {a['usage']['delta']:+d}); time delta {a['time_delta_s']:+}s; fix-round delta {a['fix_delta']:+d}",
             f"Quality: {a['quality']}", ""]
    lines += [f"Router review findings (total): {a['review_findings']}", ""]
    lines += ["| case | run | quality | usage delta | % | time delta s | fix delta |", "|---|---|---|---|---|---|---|"]
    for p in rep["per_case"]:
        pct = "-" if p["usage_delta_pct"] is None else f"{p['usage_delta_pct']:+.1f}"
        lines.append(f"| {p['case_id']} | {p['run']} | {p['quality']} | {p['usage_delta']:+d} | {pct} | "
                     f"{p['time_delta_s']:+} | {p['fix_delta']:+d} |")
    lines += ["", "Per-case means (usage tokens):", "", "| case | runs | baseline | router | delta | % | quality |",
              "|---|---|---|---|---|---|---|"]
    for m in rep["per_case_mean"]:
        pct = "-" if m["usage_delta_pct"] is None else f"{m['usage_delta_pct']:+.1f}"
        lines.append(f"| {m['case_id']} | {m['runs']} | {m['baseline_mean']:.0f} | {m['router_mean']:.0f} | "
                     f"{m['usage_delta_mean']:+.0f} | {pct} | {m['quality']} |")
    if a["excluded"]:
        lines += ["", "Excluded: " + ", ".join(f"{e['case_id']}{'#r%d' % e['run'] if 'run' in e else ''} ({e['reason']})"
                                                for e in a["excluded"])]
    if a["unpaired"]:
        lines += ["", f"Unpaired (excluded): {', '.join(a['unpaired'])}"]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="evaluation.baseline", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("report")
    rp.add_argument("runs")
    rp.add_argument("--json")
    rp.add_argument("--md")
    mk = sub.add_parser("mark", help="set requirements_met for one run (manual judgment)")
    mk.add_argument("runs")
    mk.add_argument("case_id")
    mk.add_argument("mode", choices=MODES)
    mk.add_argument("met", choices=("yes", "no"))
    mk.add_argument("--run", type=int, help="run number (required when the case has several runs of that mode)")
    args = ap.parse_args(argv)
    try:
        rows = load_records(args.runs)
        if args.cmd == "mark":
            hit = [r for r in rows if (r["case_id"], r["mode"]) == (args.case_id, args.mode)]
            if args.run is not None:
                hit = [r for r in hit if r["run"] == args.run]
            elif len({r["run"] for r in hit}) > 1:
                print(f"case {args.case_id!r} has several {args.mode} runs; pass --run K", file=sys.stderr)
                return 1
            if len(hit) > 1:
                print(f"duplicate {args.mode} runs for case {args.case_id!r}; remove extras first", file=sys.stderr)
                return 1
            if not hit:
                print(f"no {args.mode} run for case {args.case_id!r}" + (f" run {args.run}" if args.run else ""), file=sys.stderr)
                return 1
            hit[0]["requirements_met"] = args.met == "yes"
            save_records(args.runs, rows)
            return 0
        rep = report(rows)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    md = to_markdown(rep)
    for path, text in ((args.json, json.dumps(rep, ensure_ascii=False, indent=2)), (args.md, md)):
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())

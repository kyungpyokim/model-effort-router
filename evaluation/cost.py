"""Model-weighted cost of recorded runs (plan 22.3). Raw token totals stay the primary metric; this adds what
those tokens cost per model, so a run that moves work from sol to luna is not scored like one that only cuts tokens.

  python3 -m evaluation.cost RUNS.jsonl... [--prices evaluation/prices.json] [--md OUT.md]

Per run, every rollout of its root threads (main, mer's sessions, all subagents) is re-read from ~/.codex/sessions:
the growth of each `token_count` event's cumulative `total_token_usage` is attributed to the model of the latest
`turn_context` (Codex sometimes writes the same token_count twice, so `last_token_usage` would double count) (a resumed session can change model on escalation). The Jev classifier is an external API with its
own price, reported as raw tokens only. Prices: USD per 1M tokens; cached input is a subset of input, reasoning a
subset of output (verified: total_tokens = input + output).
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

from . import usage

DEFAULT_PRICES = Path(__file__).with_name("prices.json")
FIELDS = ("input", "cached_input", "cache_write", "output")


def rollout_by_model(path):
    """{model: {input, cached_input, cache_write, output}} summed over the rollout's model calls."""
    keys = {"input": "input_tokens", "cached_input": "cached_input_tokens",
            "cache_write": "cache_write_input_tokens", "output": "output_tokens"}
    out, model, prev = defaultdict(lambda: dict.fromkeys(FIELDS, 0)), None, dict.fromkeys(FIELDS, 0)
    for ev in usage._events(Path(path).read_text(encoding="utf-8", errors="replace")):
        payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
        if ev.get("type") == "turn_context":
            model = payload.get("model") or model
            continue
        total = usage._token_count_total(ev)
        if total is None:
            continue
        cur = {k: int(total.get(raw) or 0) for k, raw in keys.items()}
        u = out[model or "unknown"]
        for k in FIELDS:
            u[k] += max(cur[k] - prev[k], 0)
        prev = cur
    return {m: u for m, u in out.items() if any(u.values())}


def run_by_model(record, sessions_dir):
    by = defaultdict(lambda: dict.fromkeys(FIELDS, 0))
    for path in usage.find_rollouts(sessions_dir, record.get("thread_ids") or []):
        for model, u in rollout_by_model(path).items():
            by[model] = {k: by[model][k] + u[k] for k in FIELDS}
    return dict(by)


def usd(u, price):
    """None when the model has no price (never priced as zero)."""
    if not price:
        return None
    uncached = u["input"] - u["cached_input"] - u["cache_write"]
    return (uncached * price["input"] + u["cached_input"] * price["cached_input"]
            + u["cache_write"] * price.get("cache_write", price["input"]) + u["output"] * price["output"]) / 1e6


def run_cost(record, sessions_dir, prices):
    by = run_by_model(record, sessions_dir)
    tokens = sum(u["input"] + u["output"] for u in by.values())
    costs = {m: usd(u, prices.get(m)) for m, u in by.items()}
    unpriced = sorted(m for m, c in costs.items() if c is None)
    return {"case_id": record["case_id"], "run": record["run"], "mode": record["mode"], "tokens": tokens,
            "usd": None if unpriced or not by else sum(costs.values()), "unpriced": unpriced,
            "by_model": {m: u["input"] + u["output"] for m, u in by.items()},
            "classifier_tokens": usage.total_tokens(record["usage"]["classifier"])
            if record["usage"].get("classifier") else 0}


def summarize(rows):
    """Per (case, mode) means, then totals over cases present in every mode with a priced run."""
    acc = defaultdict(list)
    for r in rows:
        acc[(r["case_id"], r["mode"])].append(r)
    mean = lambda xs: sum(xs) / len(xs) if xs else None
    cases = sorted({c for c, _ in acc})
    modes = sorted({m for _, m in acc})
    table = {}
    for c in cases:
        for m in modes:
            runs = acc.get((c, m), [])
            priced = [r["usd"] for r in runs if r["usd"] is not None]
            table[(c, m)] = {"runs": len(runs), "tokens": mean([r["tokens"] for r in runs]),
                             "usd": mean(priced) if len(priced) == len(runs) else None}
    complete = [c for c in cases if all(table[(c, m)]["usd"] is not None for m in modes)]
    totals = {m: {"tokens": sum(table[(c, m)]["tokens"] for c in complete),
                  "usd": sum(table[(c, m)]["usd"] for c in complete)} for m in modes}
    return {"modes": modes, "cases": cases, "complete": complete, "table": table, "totals": totals}


def to_markdown(s):
    modes = s["modes"]
    head = "| case | " + " | ".join(f"{m} tokens | {m} USD" for m in modes) + " |"
    lines = [f"# Cost by model ({len(s['complete'])} cases in every mode)", "", head,
             "|---|" + "---:|" * (2 * len(modes))]
    fmt = lambda v, d: "-" if v is None else f"{v:,.{d}f}"
    for c in s["cases"]:
        lines.append(f"| {c} | " + " | ".join(f"{fmt(s['table'][(c, m)]['tokens'], 0)} | "
                                              f"{fmt(s['table'][(c, m)]['usd'], 4)}" for m in modes) + " |")
    lines.append("| **total** | " + " | ".join(f"{s['totals'][m]['tokens']:,.0f} | {s['totals'][m]['usd']:.4f}"
                                              for m in modes) + " |")
    if len(modes) == 2:
        (a, b) = modes
        ta, tb = s["totals"][a], s["totals"][b]
        if ta["tokens"] and ta["usd"]:
            lines += ["", f"{b} vs {a}: tokens {(tb['tokens'] - ta['tokens']) / ta['tokens']:+.0%}, "
                          f"USD {(tb['usd'] - ta['usd']) / ta['usd']:+.0%}"]
    return "\n".join(lines) + "\n"


def main(argv=None, sessions_dir=os.path.join(os.path.expanduser("~"), ".codex", "sessions")):
    ap = argparse.ArgumentParser(prog="evaluation.cost")
    ap.add_argument("runs", nargs="+", help="run record JSONL files (records with errors are skipped)")
    ap.add_argument("--prices", default=str(DEFAULT_PRICES))
    ap.add_argument("--md")
    args = ap.parse_args(argv)
    prices = {k: v for k, v in json.loads(Path(args.prices).read_text()).items() if not k.startswith("_")}
    rows = []
    for path in args.runs:
        for line in Path(path).read_text().splitlines():
            rec = json.loads(line)
            if rec["usage"].get("incomplete_reasons") or rec.get("error") or not rec.get("thread_ids"):
                continue
            rows.append(run_cost(rec, sessions_dir, prices))
    unpriced = sorted({m for r in rows for m in r["unpriced"]})
    if unpriced:
        print(f"no price for: {', '.join(unpriced)} (those runs have no USD)", file=sys.stderr)
    md = to_markdown(summarize(rows))
    if args.md:
        Path(args.md).write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Experimental A/B report: router.mode auto (classifier) vs policy (Main decides), from the route logs."""

import argparse
import glob
import json
import os
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from model_effort_router.logging.route_log import state_dir  # noqa: E402


def events(sdir, since):
    for path in sorted(glob.glob(os.path.join(sdir, "*.log.jsonl"))):
        rows = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict) and ev.get("ts", 0) >= since:
                    rows.append(ev)
        yield rows


def collect(sdir, since=0.0):
    groups = defaultdict(lambda: defaultdict(list))
    for rows in events(sdir, since):
        current = None  # the group of the latest route in this session
        for ev in rows:
            if ev.get("event") == "route":
                # error routes carry no mode: their later starts belong to no group
                current = groups[(ev.get("mode"), ev.get("host"))] if ev.get("mode") else None
                if current is not None:
                    current["routes"].append(ev)
            elif ev.get("event") == "subagent_start" and current is not None:
                current["starts"].append(ev)
    return groups


def spawn_advised(ev):
    """Routes where Main was told it may spawn: auto spawn/advise, policy lane table (or an explicit override's spawn)."""
    action = (ev.get("advice") or {}).get("action")
    return action in ("spawn", "advise", "policy")


def report(groups):
    print(
        f"{'mode':8}{'host':8}{'routed':>7}{'advised':>8}{'starts':>7}{'match T/F/null':>16}{'p50 ms':>8}{'cls tokens':>11}"
    )
    for (mode, host), g in sorted(groups.items(), key=lambda kv: tuple(map(str, kv[0]))):
        routed = [e for e in g["routes"] if e.get("target") == "route"]
        matched = [(s.get("correlation") or {}).get("matched") for s in g["starts"]]
        lat = [e["latency_ms"] for e in g["routes"] if "latency_ms" in e]
        tokens = sum(
            (e.get("classifier_usage") or {}).get("input_tokens", 0)
            + (e.get("classifier_usage") or {}).get("output_tokens", 0)
            for e in g["routes"]
        )
        counts = f"{matched.count(True)}/{matched.count(False)}/{matched.count(None)}"
        advised = sum(spawn_advised(e) for e in routed)
        p50 = f"{statistics.median(lat):.0f}" if lat else "-"
        print(
            f"{str(mode):8}{str(host):8}{len(routed):>7}{advised:>8}{len(g['starts']):>7}{counts:>16}{p50:>8}{tokens:>11}"
        )


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__
        + " Column 'advised' = routes whose advice allowed a spawn (auto: spawn/advise, policy: lane table)."
    )
    ap.add_argument("--since", type=float, default=0.0, help="only events at or after this unix timestamp")
    args = ap.parse_args(argv)
    report(collect(state_dir(os.environ), args.since))


if __name__ == "__main__":
    main()

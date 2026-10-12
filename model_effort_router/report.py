"""`mer report`: which model and effort each request used, with token usage, read from the session logs."""

import argparse
import glob
import math
import os
import re
import time
from collections import Counter
from datetime import datetime

from .events import iter_events
from .logging import route_log

LOG_SUFFIX = ".log.jsonl"
_SINCE = re.compile(r"(\d+)([mhd])")
_UNIT_SECONDS = {"m": 60, "h": 3600, "d": 86400}
_REPORT_EVENTS = ("route", "run", "subagent_start")
_MATCH_LABELS = {True: "matched", False: "mismatched", None: "unverified"}
_TOKEN_KEYS = (
    ("input", "input_tokens", "input"),
    ("cached", "cached_input_tokens", "cached_input"),
    ("output", "output_tokens", "output"),
)


def _tokens(ev):
    """Token counts of a route (classifier) or run (worker) event; route logs name the keys differently."""
    is_route = ev["event"] == "route"
    usage = ev.get("classifier_usage") if is_route else ev.get("usage")
    if not isinstance(usage, dict):
        return {}
    out = {label: usage.get(route_key if is_route else run_key) for label, route_key, run_key in _TOKEN_KEYS}
    return {k: v for k, v in out.items() if isinstance(v, int)}


def _fmt_tokens(tokens):
    return " ".join(f"{k} {v:,}" for k, v in tokens.items()) or "-"


def since_seconds(text):
    """argparse type for `--since`: `30m`, `12h`, or `7d` as seconds."""
    found = _SINCE.fullmatch(text)
    if not found:
        raise argparse.ArgumentTypeError("use <n>m, <n>h, or <n>d, for example 12h")
    return int(found[1]) * _UNIT_SECONDS[found[2]]


def _load(sdir, session, since=None):
    cutoff = None if since is None else time.time() - since
    events = []
    for path in sorted(glob.glob(os.path.join(sdir, "*" + LOG_SUFFIX))):
        sid = os.path.basename(path)[: -len(LOG_SUFFIX)]
        if session and not sid.startswith(session):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                events.extend({**ev, "session": sid[:8]} for ev in iter_events(f.read()))
        except OSError:
            continue
    events = [ev for ev in events if ev.get("event") in _REPORT_EVENTS]
    if cutoff is not None:
        events = [ev for ev in events if (ev.get("ts") or 0) >= cutoff]
    return sorted(events, key=lambda ev: ev.get("ts") or 0)


def _row(ev):
    """(kind, model, effort, detail) for the events that say what ran; None for the rest."""
    kind = ev["event"]
    if kind == "route":
        d = ev.get("decision") or {}
        if not d:
            return None
        model = d.get("model") or (ev.get("advice") or {}).get("routed_model")
        detail = f"{d.get('role')}/{d.get('backend')} {(ev.get('advice') or {}).get('action') or ev.get('target')}"
        return kind, model, d.get("applied_effort") or d.get("requested_effort"), detail
    if kind == "run":
        return kind, ev.get("actual_model"), ev.get("applied_effort"), f"{ev.get('role')} {ev.get('status')}"
    if kind == "subagent_start":
        agent, corr = ev.get("agent_type") or "", ev.get("correlation") or {}
        effort = agent.rpartition("effort-")[2] if "effort-" in agent else (corr.get("expected") or {}).get("effort")
        return "subagent", ev.get("model"), effort, f"{agent} matched={corr.get('matched')}"
    return None


def _join(counter, empty="none"):
    return " · ".join(f"{k} {n}" for k, n in counter.most_common()) or empty


def _classifier_lines(events):
    routes = [ev for ev in events if ev["event"] == "route"]
    if not routes:
        return []
    errors = sum(ev.get("target") == "error" for ev in routes)
    fallbacks = sum(bool(ev.get("classifier_fallback")) for ev in routes)
    times = sorted(t for ev in routes if isinstance(t := ev.get("latency_ms"), (int, float)))
    line = f"classifier: {len(routes)} routes · {errors} errors · {fallbacks} fallbacks"
    if times:
        p95 = times[min(len(times), math.ceil(0.95 * len(times))) - 1]
        line += f" · latency avg {sum(times) / len(times):,.0f} ms, p95 {p95:,.0f} ms"
    causes = Counter(c for ev in routes for c in ev.get("classifier_causes") or ())
    return [line, *([f"  causes: {_join(causes)}"] if causes else [])]


def main(args, *, env, out):
    events = _load(route_log.state_dir(env), args.session, args.since)
    if not events:
        print("no routed requests in the logs", file=out)
        return 0
    rows = [(ev, r) for ev in events if (r := _row(ev))]
    for ev, (kind, model, effort, detail) in rows[-args.limit :]:
        when = datetime.fromtimestamp(ev["ts"]).strftime("%m-%d %H:%M") if ev.get("ts") else "-"
        print(
            f"{when}  {ev['session']}  {kind:<8} {model or '-'}  {effort or '-'}  {detail}  [{_fmt_tokens(_tokens(ev))}]",
            file=out,
        )
    routed = Counter((r[1], r[2] or "-") for _, r in rows if r[0] == "route" and r[1])  # no_route has no model
    if routed:
        print("\nrouted (model, effort):", file=out)
    for (model, effort), n in routed.most_common():
        print(f"  {n:>4}  {model}  {effort}", file=out)
    actions = Counter(a for ev in events if ev["event"] == "route" and (a := (ev.get("advice") or {}).get("action")))
    matches = Counter(
        _MATCH_LABELS.get((ev.get("correlation") or {}).get("matched"), "unverified")
        for ev in events
        if ev["event"] == "subagent_start"
    )
    print(f"advice: {_join(actions)}\nsubagents: {_join(matches)}", file=out)
    for line in _classifier_lines(events):
        print(line, file=out)
    for label, kind in (("classifier", "route"), ("worker", "run")):
        total = Counter()
        for ev, r in rows:
            if r[0] == kind:
                total.update(_tokens(ev))
        print(f"{label} tokens: {_fmt_tokens(dict(total))}", file=out)
    return 0

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
_REPORT_EVENTS = ("route", "run", "subagent_start", "subagent_stop", "context_refresh", "error")
_MATCH_LABELS = {True: "matched", False: "mismatched", None: "unverified"}
_TOKEN_KEYS = (
    ("input", "input_tokens", "input"),
    ("cached", "cached_input_tokens", "cached_input"),
    ("output", "output_tokens", "output"),
)


def _tokens(ev):
    """Token counts of classifier, worker, or context refresh usage."""
    long_keys = ev["event"] in ("route", "context_refresh")
    usage = ev.get("classifier_usage") if ev["event"] == "route" else ev.get("usage")
    if not isinstance(usage, dict):
        return {}
    out = {label: usage.get(route_key if long_keys else run_key) for label, route_key, run_key in _TOKEN_KEYS}
    return {k: v for k, v in out.items() if isinstance(v, int)}


def _fmt_tokens(tokens):
    return " ".join(f"{k} {v:,}" for k, v in tokens.items()) or "-"


def since_seconds(text):
    """argparse type for `--since`: `30m`, `12h`, or `7d` as seconds."""
    found = _SINCE.fullmatch(text)
    if not found:
        raise argparse.ArgumentTypeError("use <n>m, <n>h, or <n>d, for example 12h")
    return int(found[1]) * _UNIT_SECONDS[found[2]]


def limit_count(text):
    """argparse type for `--limit`: a row count, where 0 lists no rows and shows only the summary."""
    try:
        count = int(text)
    except ValueError:
        count = -1
    if count < 0:
        raise argparse.ArgumentTypeError("use a whole number, 0 or more")
    return count


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
            detail = ev.get("target") or "route"
            if ev.get("error_type"):
                detail += f" {ev['error_type']}"
            if ev.get("stage"):
                detail += f" stage={ev['stage']}"
            if ev.get("configured_backend"):
                detail += f" backend={ev['configured_backend']}"
            return "route", None, None, detail
        model = d.get("model") or (ev.get("advice") or {}).get("routed_model")
        advice = ev.get("advice") or {}
        detail = f"{d.get('role')}/{d.get('backend')} {advice.get('action') or ev.get('target')}"
        main = "/".join(filter(None, (advice.get("main_model"), ev.get("main_effort"))))
        detail += f" main={main}" if main else ""
        return kind, model, d.get("applied_effort") or d.get("requested_effort"), detail
    if kind == "run":
        detail = f"{ev.get('role')} {ev.get('status')}"
        detail += f" stage={ev['failure_stage']}" if ev.get("failure_stage") else ""
        detail += f" error={ev['error_type']}" if ev.get("error_type") else ""
        attempts = ev.get("attempts")
        checks = [
            f"{a.get('applied_effort')}:{a.get('verification_status')}"
            + (
                f"/{a['verification_duration_s']:.1f}s"
                if isinstance(a.get("verification_duration_s"), (int, float))
                else ""
            )
            for a in (attempts if isinstance(attempts, list) else [])
            if isinstance(a, dict) and a.get("verification_status")
        ]
        detail += f" checks={','.join(checks)}" if checks else ""
        return kind, ev.get("actual_model"), ev.get("applied_effort"), detail
    if kind in ("subagent_start", "subagent_stop"):
        agent, corr = ev.get("agent_type") or "", ev.get("correlation") or {}
        effort = agent.rpartition("effort-")[2] if "effort-" in agent else (corr.get("expected") or {}).get("effort")
        row_kind = "subagent" if kind == "subagent_start" else kind
        return row_kind, ev.get("model"), effort, f"{agent} matched={corr.get('matched')}"
    if kind == "context_refresh":
        detail = f"turns={ev.get('turns', '-')}"
        if isinstance(ev.get("latency_ms"), (int, float)):
            detail += f" latency={ev['latency_ms']:,.0f}ms"
        return "context", ev.get("host"), None, detail
    if kind == "error":
        detail = ev.get("code") or "error"
        if ev.get("stage"):
            detail += f" stage={ev['stage']}"
        if ev.get("type"):
            detail += f" type={ev['type']}"
        if ev.get("reason"):
            detail += f" reason={ev['reason']}"
        return kind, None, None, detail
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


def _workflow_lines(events):
    lines = []
    runs = [ev for ev in events if ev["event"] == "run"]
    if runs:
        lines.append(f"runs: {_join(Counter(ev.get('status') or 'unknown' for ev in runs))}")
    starts = sum(ev["event"] == "subagent_start" for ev in events)
    stops = sum(ev["event"] == "subagent_stop" for ev in events)
    if starts or stops:
        lines.append(f"subagent lifecycle: {starts} started · {stops} stopped")
    refreshes = [ev for ev in events if ev["event"] == "context_refresh"]
    refresh_errors = [ev for ev in events if ev["event"] == "error" and ev.get("code") == "context_refresh_failed"]
    if refreshes or refresh_errors:
        times = [ev["latency_ms"] for ev in refreshes if isinstance(ev.get("latency_ms"), (int, float))]
        line = f"context refresh: {len(refreshes)} completed · {len(refresh_errors)} errors"
        if times:
            line += f" · latency avg {sum(times) / len(times):,.0f} ms"
        lines.append(line)
    failures = Counter()
    for ev in events:
        kind = ev.get("event")
        if kind == "route" and ev.get("target") == "error":
            failures[f"routing/{ev.get('error_type') or 'unknown'}"] += 1
        elif kind == "error":
            label = ev.get("reason") or ev.get("code") or "error"
            failures[f"{ev.get('stage') or 'workflow'}/{label}"] += 1
        elif kind == "run" and ev.get("status") in ("error", "verification_failed"):
            failures[f"{ev.get('failure_stage') or 'execution'}/{ev.get('error_type') or ev.get('status')}"] += 1
    if failures:
        lines.append(f"workflow failures: {_join(failures)}")
    return lines


def main(args, *, env, out):
    events = _load(route_log.state_dir(env), args.session, args.since)
    if not events:
        print("no routed requests in the logs", file=out)
        return 0
    rows = [(ev, r) for ev in events if (r := _row(ev))]
    shown = rows[max(0, len(rows) - args.limit) :]
    for ev, (kind, model, effort, detail) in shown:
        when = datetime.fromtimestamp(ev["ts"]).strftime("%m-%d %H:%M") if ev.get("ts") else "-"
        print(
            f"{when}  {ev['session']}  {kind:<8} {model or '-'}  {effort or '-'}  {detail}  [{_fmt_tokens(_tokens(ev))}]",
            file=out,
        )
    summary = []
    routed = Counter((r[1], r[2] or "-") for _, r in rows if r[0] == "route" and r[1])  # no_route has no model
    if routed:
        summary.append("routed (model, effort):")
    summary.extend(f"  {n:>4}  {model}  {effort}" for (model, effort), n in routed.most_common())
    actions = Counter(a for ev in events if ev["event"] == "route" and (a := (ev.get("advice") or {}).get("action")))
    matches = Counter(
        _MATCH_LABELS.get((ev.get("correlation") or {}).get("matched"), "unverified")
        for ev in events
        if ev["event"] == "subagent_start"
    )
    summary.extend(
        [
            f"advice: {_join(actions)}",
            f"subagents: {_join(matches)}",
            *_classifier_lines(events),
            *_workflow_lines(events),
        ]
    )
    for label, kind in (("classifier", "route"), ("worker", "run"), ("context refresh", "context_refresh")):
        if kind == "context_refresh" and not any(ev["event"] == kind for ev in events):
            continue
        total = Counter()
        for ev, r in rows:
            if ev["event"] == kind:
                total.update(_tokens(ev))
        summary.append(f"{label} tokens: {_fmt_tokens(dict(total))}")
    if shown:
        print(file=out)  # blank line between the rows and the summary
    print("\n".join(summary), file=out)
    return 0

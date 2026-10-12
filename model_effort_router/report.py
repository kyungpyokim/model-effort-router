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


def _route_error_row(ev):
    detail = ev.get("target") or "route"
    if ev.get("error_type"):
        detail += f" {ev['error_type']}"
    if ev.get("stage"):
        detail += f" stage={ev['stage']}"
    if ev.get("configured_backend"):
        detail += f" backend={ev['configured_backend']}"
    return "route", None, None, detail


def _route_row(ev):
    decision = ev.get("decision") or {}
    if not decision:
        return _route_error_row(ev)
    advice = ev.get("advice") or {}
    model = decision.get("model") or advice.get("routed_model")
    effort = decision.get("applied_effort") or decision.get("requested_effort")
    detail = f"{decision.get('role')}/{decision.get('backend')} {advice.get('action') or ev.get('target')}"
    main = "/".join(filter(None, (advice.get("main_model"), ev.get("main_effort"))))
    if main:
        detail += f" main={main}"
    return "route", model, effort, detail


def _verification_checks(attempts):
    if not isinstance(attempts, list):
        return []
    checks = []
    for attempt in attempts:
        if not isinstance(attempt, dict) or not attempt.get("verification_status"):
            continue
        check = f"{attempt.get('applied_effort')}:{attempt.get('verification_status')}"
        duration = attempt.get("verification_duration_s")
        if isinstance(duration, (int, float)):
            check += f"/{duration:.1f}s"
        checks.append(check)
    return checks


def _run_row(ev):
    detail = f"{ev.get('role')} {ev.get('status')}"
    if ev.get("failure_stage"):
        detail += f" stage={ev['failure_stage']}"
    if ev.get("error_type"):
        detail += f" error={ev['error_type']}"
    checks = _verification_checks(ev.get("attempts"))
    if checks:
        detail += f" checks={','.join(checks)}"
    return "run", ev.get("actual_model"), ev.get("applied_effort"), detail


def _subagent_row(ev):
    agent = ev.get("agent_type") or ""
    correlation = ev.get("correlation") or {}
    expected = correlation.get("expected") or {}
    effort = agent.rpartition("effort-")[2] if "effort-" in agent else expected.get("effort")
    kind = "subagent" if ev["event"] == "subagent_start" else "subagent_stop"
    return kind, ev.get("model"), effort, f"{agent} matched={correlation.get('matched')}"


def _context_refresh_row(ev):
    detail = f"turns={ev.get('turns', '-')}"
    latency = ev.get("latency_ms")
    if isinstance(latency, (int, float)):
        detail += f" latency={latency:,.0f}ms"
    return "context", ev.get("host"), None, detail


def _error_row(ev):
    detail = ev.get("code") or "error"
    for field in ("stage", "type", "reason"):
        if ev.get(field):
            detail += f" {field}={ev[field]}"
    return "error", None, None, detail


def _row(ev):
    """Return (kind, model, effort, detail) for a reportable event."""
    kind = ev["event"]
    if kind == "route":
        return _route_row(ev)
    if kind == "run":
        return _run_row(ev)
    if kind in ("subagent_start", "subagent_stop"):
        return _subagent_row(ev)
    if kind == "context_refresh":
        return _context_refresh_row(ev)
    if kind == "error":
        return _error_row(ev)
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


def _run_summary(events):
    runs = [ev for ev in events if ev["event"] == "run"]
    if not runs:
        return None
    statuses = Counter(ev.get("status") or "unknown" for ev in runs)
    return f"runs: {_join(statuses)}"


def _subagent_summary(events):
    starts = sum(ev["event"] == "subagent_start" for ev in events)
    stops = sum(ev["event"] == "subagent_stop" for ev in events)
    if not starts and not stops:
        return None
    return f"subagent lifecycle: {starts} started · {stops} stopped"


def _context_refresh_summary(events):
    refreshes = [ev for ev in events if ev["event"] == "context_refresh"]
    errors = sum(ev["event"] == "error" and ev.get("code") == "context_refresh_failed" for ev in events)
    if not refreshes and not errors:
        return None
    times = [ev["latency_ms"] for ev in refreshes if isinstance(ev.get("latency_ms"), (int, float))]
    line = f"context refresh: {len(refreshes)} completed · {errors} errors"
    if times:
        line += f" · latency avg {sum(times) / len(times):,.0f} ms"
    return line


def _workflow_failure(ev):
    kind = ev.get("event")
    if kind == "route" and ev.get("target") == "error":
        return f"routing/{ev.get('error_type') or 'unknown'}"
    if kind == "error":
        label = ev.get("reason") or ev.get("code") or "error"
        return f"{ev.get('stage') or 'workflow'}/{label}"
    if kind == "run" and ev.get("status") in ("error", "verification_failed"):
        stage = ev.get("failure_stage") or "execution"
        error = ev.get("error_type") or ev.get("status")
        return f"{stage}/{error}"
    return None


def _workflow_failure_summary(events):
    failures = Counter(failure for ev in events if (failure := _workflow_failure(ev)))
    return f"workflow failures: {_join(failures)}" if failures else None


def _workflow_lines(events):
    summaries = (
        _run_summary(events),
        _subagent_summary(events),
        _context_refresh_summary(events),
        _workflow_failure_summary(events),
    )
    return [line for line in summaries if line]


def _report_rows(events):
    return [(ev, row) for ev in events if (row := _row(ev))]


def _recent_rows(rows, limit):
    return rows[max(0, len(rows) - limit) :]


def _format_row(ev, row):
    kind, model, effort, detail = row
    when = datetime.fromtimestamp(ev["ts"]).strftime("%m-%d %H:%M") if ev.get("ts") else "-"
    return f"{when}  {ev['session']}  {kind:<8} {model or '-'}  {effort or '-'}  {detail}  [{_fmt_tokens(_tokens(ev))}]"


def _print_rows(rows, out):
    for event, row in rows:
        print(_format_row(event, row), file=out)


def _advice_summary(events):
    actions = Counter()
    for event in events:
        if event["event"] == "route":
            action = (event.get("advice") or {}).get("action")
            if action:
                actions[action] += 1
    return f"advice: {_join(actions)}"


def _subagent_match_summary(events):
    matches = Counter(
        _MATCH_LABELS.get((ev.get("correlation") or {}).get("matched"), "unverified")
        for ev in events
        if ev["event"] == "subagent_start"
    )
    return f"subagents: {_join(matches)}"


def _routed_models_summary(rows):
    routed = Counter((row[1], row[2] or "-") for _, row in rows if row[0] == "route" and row[1])
    lines = ["routed (model, effort):"] if routed else []
    lines.extend(f"  {count:>4}  {model}  {effort}" for (model, effort), count in routed.most_common())
    return lines


def _token_summary_lines(events, rows):
    lines = []
    summaries = (("classifier", "route"), ("worker", "run"), ("context refresh", "context_refresh"))
    for label, kind in summaries:
        if kind == "context_refresh" and not any(ev["event"] == kind for ev in events):
            continue
        total = Counter()
        for event, _ in rows:
            if event["event"] == kind:
                total.update(_tokens(event))
        lines.append(f"{label} tokens: {_fmt_tokens(dict(total))}")
    return lines


def _summary_lines(events, rows):
    lines = _routed_models_summary(rows)
    lines.extend((_advice_summary(events), _subagent_match_summary(events)))
    lines.extend(_classifier_lines(events))
    lines.extend(_workflow_lines(events))
    lines.extend(_token_summary_lines(events, rows))
    return lines


def main(args, *, env, out):
    events = _load(route_log.state_dir(env), args.session, args.since)
    if not events:
        print("no routed requests in the logs", file=out)
        return 0
    rows = _report_rows(events)
    shown = _recent_rows(rows, args.limit)
    _print_rows(shown, out)
    if shown:
        print(file=out)  # blank line between the rows and the summary
    print("\n".join(_summary_lines(events, rows)), file=out)
    return 0

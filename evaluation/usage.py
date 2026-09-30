"""Token usage aggregation for one run (spec 22.3): main session + classifier calls + every subagent.

`codex exec --json` does not report subagent usage, so children are read from their rollout files.
Normalized usage: {"input", "cached_input", "output", "reasoning_output"}; total = input + output
(assumption: cached is a subset of input, reasoning a subset of output).

ASSUMED, UNVERIFIED (spikes/phase0 summaries dropped these events; see _token_count_total):
  rollout line  {"type": "event_msg", "payload": {"type": "token_count",
                 "info": {"total_token_usage": {input_tokens, cached_input_tokens, output_tokens,
                          reasoning_output_tokens, total_tokens}} | null}}
  total_token_usage is cumulative per thread, so the last non-null one is the thread total.
Verified from spike evidence: exec stream `turn.completed.usage`, rollout `session_meta.payload`
(`session_id` = root thread, `thread_source`, `agent_path`, `parent_thread_id`).
"""
import json
from pathlib import Path

KEYS = {"input_tokens": "input", "cached_input_tokens": "cached_input",
        "output_tokens": "output", "reasoning_output_tokens": "reasoning_output"}
STAGE_PREFIX = "mer-"


def normalize(raw):
    raw = raw if isinstance(raw, dict) else {}
    return {short: int(raw.get(long) or 0) for long, short in KEYS.items()}


def add(a, b):
    return {k: a[k] + b[k] for k in a}


def total_tokens(u):
    return u["input"] + u["output"]


def _events(text):
    for line in text.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict):
            yield ev


def exec_stream_usage(text):
    """(thread_id, summed turn.completed usage) of a `codex exec --json` stdout."""
    thread_id, total = None, normalize(None)
    for ev in _events(text):
        if ev.get("type") == "thread.started":
            thread_id = ev.get("thread_id")
        elif ev.get("type") == "turn.completed":
            total = add(total, normalize(ev.get("usage")))
    return thread_id, total


def _token_count_total(ev):
    """The isolated place that knows the (assumed) rollout token_count shape; None if not one."""
    payload = ev.get("payload")
    if ev.get("type") != "event_msg" or not isinstance(payload, dict) or payload.get("type") != "token_count":
        return None
    info = payload.get("info")
    total = info.get("total_token_usage") if isinstance(info, dict) else None
    return total if isinstance(total, dict) else None


def read_rollout(path):
    meta, last = {}, None
    for ev in _events(Path(path).read_text(encoding="utf-8", errors="replace")):
        if ev.get("type") == "session_meta" and isinstance(ev.get("payload"), dict):
            meta = ev["payload"]
        counted = _token_count_total(ev)
        if counted is not None:
            last = counted
    return {"id": meta.get("id"), "session_id": meta.get("session_id"),
            "thread_source": meta.get("thread_source"), "agent_path": meta.get("agent_path"),
            "usage": normalize(last) if last is not None else None}  # None = no token_count seen


def stage_of(agent_path):
    name = str(agent_path or "").rsplit("/", 1)[-1]
    return name[len(STAGE_PREFIX):] if name.startswith(STAGE_PREFIX) else "other"


def _first_session_id(path):
    """session_id from the first line only (session_meta is the first rollout line)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            ev = json.loads(f.readline())
    except (OSError, ValueError):
        return None
    payload = ev.get("payload") if isinstance(ev, dict) and ev.get("type") == "session_meta" else None
    return payload.get("session_id") if isinstance(payload, dict) else None


def find_rollouts(sessions_dir, root_session_id, since_mtime=None):
    """Rollout files (main + all subagents) of one root session, modified at/after `since_mtime` (run start).
    Only the first line is read to filter; matches are parsed later by the caller."""
    base = Path(sessions_dir)
    if not base.is_dir():
        return []
    out = []
    for p in sorted(base.rglob("rollout-*.jsonl")):
        try:
            if since_mtime is not None and p.stat().st_mtime < since_mtime:
                continue
        except OSError:
            continue
        if _first_session_id(p) == root_session_id:
            out.append(p)
    return out


def aggregate(exec_text, rollout_paths, classifier=None):
    """Everything a run consumed. The exec stream is the main session when given (no double count with
    its rollout); otherwise the non-subagent rollouts are."""
    main = exec_stream_usage(exec_text)[1] if exec_text is not None else normalize(None)
    stages, missing, children = {}, [], 0
    for path in rollout_paths:
        r = read_rollout(path)
        if r["thread_source"] == "subagent":
            children += 1
            stage = stage_of(r["agent_path"])
            if r["usage"] is None:
                missing.append(stage)  # never count as zero: the total would silently understate
                continue
            stages[stage] = add(stages.get(stage, normalize(None)), r["usage"])
        elif exec_text is None and r["usage"] is not None:
            main = add(main, r["usage"])
    total = total_tokens(main) + sum(total_tokens(s) for s in stages.values()) + \
        (total_tokens(classifier) if classifier else 0)
    return {"orchestrator": main, "classifier": classifier, "stages": stages, "total": total,
            "subagent_rollouts": children, "stages_without_usage": missing}

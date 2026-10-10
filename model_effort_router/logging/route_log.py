"""Append-only JSONL route log, one file per session (spec 21). Never stores prompt text, only hash + length."""

import hashlib
import json
import os
import re
import time

STATE_ENV = "MER_STATE_DIR"


def state_dir(env):
    if env.get(STATE_ENV):
        return env[STATE_ENV]
    base = env.get("XDG_STATE_HOME") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "model-effort-router")


def log_path(sdir, session_id):
    """Readable prefix + hash of the raw id: `a/b` and `a_b` never share a file, `../x` stays inside the dir."""
    raw = str(session_id)
    prefix = re.sub(r"[^A-Za-z0-9._-]", "_", raw)[:64] or "_unknown"
    return os.path.join(sdir, f"{prefix}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:8]}.log.jsonl")


def append(state_dir, session_id, event):
    os.makedirs(state_dir, exist_ok=True)
    line = json.dumps({"ts": round(time.time(), 3), **event}, ensure_ascii=False)
    with open(log_path(state_dir, session_id), "a", encoding="utf-8") as f:
        f.write(line + "\n")


TAIL_BYTES = 64 * 1024  # bounded read: the latest event sits at the end of an append-only file


def last_event(state_dir, session_id, name, **fields):
    """Most recent event called `name` (with equal `fields`) within the log's tail, else None. Never raises."""
    try:
        with open(log_path(state_dir, session_id), "rb") as f:
            size = f.seek(0, os.SEEK_END)
            f.seek(max(0, size - TAIL_BYTES - 1))  # one byte of look-behind: a cut line always has a partial head
            lines = f.read().split(b"\n")  # bytes, not str.splitlines: U+2028 or \x85 inside a value is not a break
        for raw in reversed(lines[1:] if size > TAIL_BYTES else lines):
            try:
                ev = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            if isinstance(ev, dict) and ev.get("event") == name and all(ev.get(k) == v for k, v in fields.items()):
                return ev
    except Exception:
        pass
    return None


def prompt_fingerprint(prompt):
    return {"prompt_sha": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12], "prompt_len": len(prompt)}


def error_event(exc, *, latency_ms, prompt, configured_backend, timeout_clamped=False):
    """A prompt whose routing raised: type name only, since messages can carry config or prompt text."""
    ev = {
        "event": "route",
        "target": "error",
        "error_type": type(exc).__name__,
        "configured_backend": configured_backend,
        "latency_ms": round(latency_ms, 1),
        **prompt_fingerprint(prompt),
    }
    if timeout_clamped:
        ev["timeout_clamped"] = True
    return ev


def route_event(
    plan, *, latency_ms, prompt, configured_backend, timeout_clamped=False, host=None, turn_id=None, advice=None
):
    decision = plan.decision
    ev = {
        "event": "route",
        "target": plan.target,
        "mode": plan.mode,
        "override_rejected": plan.override_rejected,
        "latency_ms": round(latency_ms, 1),
        **prompt_fingerprint(prompt),
    }
    if timeout_clamped:
        ev["timeout_clamped"] = True
    ev.update({k: v for k, v in (("host", host), ("turn_id", turn_id), ("advice", advice)) if v is not None})
    if plan.classifier_usage_missing:
        ev["classifier_usage"] = None  # a model was called but its usage is unknown (absent key = no model call)
    elif plan.classifier_usage:
        ev["classifier_usage"] = dict(plan.classifier_usage)  # token counts only
    if decision:
        ev["decision"] = {
            "role": decision.role,
            "effort": plan.applied_effort or decision.effort,
            "backend": decision.backend,
            "confidence": decision.confidence,
            "reason_code": decision.reason_code,
            "risk_flags": list(plan.risk_flags),
            "model": plan.model,
            "requested_effort": plan.requested_effort or decision.effort,
            "applied_effort": plan.applied_effort,
        }
        if decision.target:
            ev["decision"]["target"] = decision.target
        if decision.backend != "explicit":
            ev["classifier_fallback"] = decision.backend != configured_backend
    return ev

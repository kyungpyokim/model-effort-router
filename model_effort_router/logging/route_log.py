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


def prompt_fingerprint(prompt):
    return {"prompt_sha": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12], "prompt_len": len(prompt)}


def route_event(plan, *, latency_ms, prompt, configured_backend, timeout_clamped=False, turn_settings=None):
    decision = plan.decision
    ev = {"event": "route", "target": plan.target, "mode": plan.mode,
          "target_source": plan.target_source, "override_rejected": plan.override_rejected, "latency_ms": round(latency_ms, 1),
          **prompt_fingerprint(prompt)}
    if timeout_clamped:
        ev["timeout_clamped"] = True
    if turn_settings:
        ev["turn_settings"] = dict(turn_settings)
    if plan.classifier_usage_missing:
        ev["classifier_usage"] = None  # a model was called but its usage is unknown (absent key = no model call)
    elif plan.classifier_usage:
        ev["classifier_usage"] = dict(plan.classifier_usage)  # token counts only
    if decision:
        ev["decision"] = {
            "level": decision.level, "backend": decision.backend, "confidence": decision.confidence,
            "reason_codes": list(decision.reason_codes), "risk_flags": list(decision.risk_flags),
            "distribution": dict(decision.distribution) if decision.distribution else None,
        }
        ev["fallback"] = decision.backend != configured_backend
    return ev

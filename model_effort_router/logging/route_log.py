"""Append-only JSONL route log, one file per session (spec 21). Never stores prompt text, only hash + length."""
import hashlib
import json
import os
import time

from ..host.state import log_path


def append(state_dir, session_id, event):
    os.makedirs(state_dir, exist_ok=True)
    line = json.dumps({"ts": round(time.time(), 3), **event}, ensure_ascii=False)
    with open(log_path(state_dir, session_id), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def prompt_fingerprint(prompt):
    return {"prompt_sha": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12], "prompt_len": len(prompt)}


def route_event(plan, state, *, latency_ms, prompt, configured_backend, timeout_clamped=False):
    decision = plan.decision
    ev = {"event": "route", "target": plan.target, "mode": plan.mode,
          "override_rejected": plan.override_rejected, "latency_ms": round(latency_ms, 1),
          **prompt_fingerprint(prompt)}
    if timeout_clamped:
        ev["timeout_clamped"] = True
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
    if plan.policy:
        ev["applied_rules"] = list(plan.policy.applied_rules)
    if state:
        ev["stages"] = [{"stage": n, "tier": s["tier"], "model": s["model"],
                         "requested_effort": s["requested_effort"], "applied_effort": s["effort"]}
                        for n, s in state["stages"].items()]
    return ev


REVIEW_VERDICTS = ("approved", "changes_requested")


def review_event(verdict, findings=None, fix_count=None):
    """Review outcome (spec 21): verdict and counts only, never review text."""
    if verdict not in REVIEW_VERDICTS:
        raise ValueError(f"verdict must be one of {REVIEW_VERDICTS}, got {verdict!r}")
    ev = {"event": "review", "verdict": verdict}
    if findings is not None:
        ev["findings"] = findings
    if fix_count is not None:
        ev["fix_count"] = fix_count
    return ev

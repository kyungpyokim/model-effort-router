"""mer run flow (spec 3.4): implement session -> Test Gate -> cascade escalation -> independent review.

All I/O is injected (runner, gate_fn, diff_fn, emit) so the flow is testable without codex or git.
"""
import time

from . import review as rv
from .adapters.codex import CodexConfig, resolve
from .host import codex_exec as cx
from .policy.session import REVIEW_DEFAULT

GATE_TEXT_MAX = 2000
USAGE_KEYS = ("input", "cached_input", "output", "reasoning_output")
PLAN_FIRST = "First write a short plan, then implement it. "
WRAP_UP = "When finished, end with a short summary of the changes."


def _gate_summary(gate):
    bad = [f"{k}: {c.get('command', '')}\n{(c.get('output_tail') or c.get('reason') or '')[-GATE_TEXT_MAX:]}"
           for k, c in gate.get("checks", {}).items() if c.get("status") == "failed"]
    return "\n\n".join(bad) or gate.get("error", "the gate failed")


def _sum_usage(calls):
    total = dict.fromkeys(USAGE_KEYS, 0)
    for c in calls:
        for k in USAGE_KEYS:
            total[k] += (c["usage"] or {}).get(k, 0)
    return {**total, "total": total["input"] + total["output"],
            "missing": sum(c["usage"] is None for c in calls)}


def _profile(call):
    return {k: call[k] for k in ("tier", "model", "requested_effort", "applied_effort")} if call else None


class _Flow:
    def __init__(self, request, sp, cwd, runner, env, gate_fn, diff_fn, emit, max_esc, timeout_s, config, clock):
        self.request, self.sp, self.cwd, self.runner = request, sp, cwd, runner
        self.env, self.gate_fn, self.diff_fn, self.emit = cx.session_env(env), gate_fn, diff_fn, emit
        self.max_esc, self.timeout_s, self.config, self.clock = max_esc, timeout_s, config, clock
        self.calls, self.tracker = [], cx.UsageTracker()
        self.thread, self.esc, self.profile, self.message = None, 0, sp.start, None
        self.gate = None
        self.review = {"verdict": None, "findings": None, "skipped": "not required"}
        self.review_required = bool(sp.review)

    def call(self, role, argv, profile, thread=None):
        t0, r = self.clock(), resolve(profile, self.config)
        rec = {"role": role, "thread_id": thread, "tier": profile.tier, "model": r.model,
               "requested_effort": r.requested_effort, "applied_effort": r.applied_effort, "usage": None}
        self.calls.append(rec)  # before running: a timed-out call still shows up (usage None = missing)
        try:
            stream = cx.parse_stream(self.runner(argv, cwd=self.cwd, env=self.env, timeout_s=self.timeout_s))
        finally:
            rec["wall_s"] = round(self.clock() - t0, 3)
        tid = stream.thread_id or thread
        # no thread id: a fresh session's cumulative usage is its own (never share a tracker slot)
        rec.update(thread_id=tid, usage=self.tracker.delta(tid, stream.usage) if tid else stream.usage)
        return stream, rec

    def run_gate(self):
        try:
            self.gate = self.gate_fn(self.cwd)
        except Exception as exc:  # a broken gate must not look like a failed test run
            self.gate = {"overall": "incomplete", "checks": {}, "error": f"{type(exc).__name__}: {exc}"[:300]}
        self.emit({"event": "gate", "overall": self.gate["overall"],
                   "checks": {k: v.get("status") for k, v in self.gate.get("checks", {}).items()}})
        return self.gate

    def can_escalate(self):
        return bool(self.thread) and self.esc < self.max_esc and self.esc < len(self.sp.ladder)

    def escalate(self, reason, text):
        profile = self.sp.ladder[self.esc]
        stream, rec = self.call("escalate", cx.resume_argv(profile, self.thread, text, self.config), profile, self.thread)
        self.esc, self.profile, self.message = self.esc + 1, profile, stream.text or self.message
        self.emit({"event": "escalate", "reason": reason, "index": self.esc, **rec})

    def gate_loop(self):
        gate = self.run_gate()
        while gate["overall"] == "failed" and self.can_escalate():
            self.escalate("gate_failed", f"The Test Gate failed. Fix it, then stop.\n\n{_gate_summary(gate)}")
            gate = self.run_gate()
        return gate

    def run_review(self, profile):
        diff = self.diff_fn(self.cwd)
        if not diff.get("is_repo"):
            self.review = {"verdict": None, "findings": None, "skipped": "not a git repository"}
            return False
        prompt = rv.review_prompt(self.request, diff, self.gate)
        stream, rec = self.call("review", cx.session_argv(profile, prompt, "read-only", self.config), profile)
        self.emit({"event": "session_start", **rec})
        verdict, findings = rv.parse_verdict(stream.text)
        self.review = {"verdict": verdict, "findings": findings, "skipped": None, "text": stream.text or ""}
        self.emit({"event": "review", "verdict": verdict, "findings": findings, "thread_id": rec["thread_id"],
                   "usage": rec["usage"]})
        return True

    def implement(self):
        sp = self.sp
        prompt = f"{self.request}\n\n{PLAN_FIRST if sp.plan_first else ''}{WRAP_UP}"
        stream, rec = self.call("implement", cx.session_argv(sp.start, prompt, "workspace-write", self.config), sp.start)
        self.thread, self.message = rec["thread_id"], stream.text
        self.emit({"event": "session_start", **rec})
        gate = self.gate_loop()
        if sp.review and gate["overall"] == "failed":
            self.review["skipped"] = "gate failed"
        elif sp.review:
            self.run_review(sp.review)  # changes_requested ends the run: findings are reported, no fix loop
        return self.outcome()

    def review_only(self):
        if not self.diff_fn(self.cwd).get("is_repo"):
            return {"status": "no_git_repo", "exit_code": 2,
                    "message": "mer: not a git repository, nothing to diff for the review"}
        self.review_required = True
        self.run_gate()
        self.run_review(self.sp.review or REVIEW_DEFAULT)
        return self.outcome()

    def plan_only(self):
        prompt = f"{self.request}\n\nWrite an implementation plan only. Do not modify any files."
        stream, rec = self.call("plan", cx.session_argv(self.sp.plan_profile, prompt, "read-only", self.config),
                                self.sp.plan_profile)
        self.emit({"event": "session_start", **rec})
        return {"status": "ok", "exit_code": 0, "message": stream.text}

    def outcome(self):
        if self.gate and self.gate["overall"] == "failed":
            status = "gate_failed"
        elif self.review["verdict"] == "changes_requested":
            status = "changes_requested"
        elif self.review_required and self.review["verdict"] != "approved":  # a required review never passes silently
            status = "review_skipped" if self.review["skipped"] else "review_unknown"
        else:
            status = "ok"
        return {"status": status, "exit_code": 0 if status == "ok" else 1, "message": self.message}


def run_flow(request, sp, *, cwd, runner, env, gate_fn, diff_fn, emit, target="route", max_escalations=2,
             timeout_s=1200, config=CodexConfig(), clock=time.monotonic):
    flow = _Flow(request, sp, cwd, runner, env, gate_fn, diff_fn, emit, max_escalations, timeout_s, config, clock)
    t0 = clock()
    try:
        result = getattr(flow, {"plan_only": "plan_only", "review_only": "review_only"}.get(target, "implement"))()
    except Exception as exc:  # timeout, codex crash: report, never traceback
        result = {"status": "error", "exit_code": 1, "error": f"{type(exc).__name__}: {exc}"[:300],
                  "message": flow.message}
    review = {**flow.review, **({"text": flow.review["text"][-rv.FINDINGS_MAX:]} if "text" in flow.review else {})}
    out = {**result, "level": sp.level, "target": target, "escalations": flow.esc, "gate": (flow.gate or {}).get("overall"),
           "review": review, "calls": flow.calls, "usage": _sum_usage(flow.calls),
           "threads": list(dict.fromkeys(c["thread_id"] for c in flow.calls if c["thread_id"])),
           "profile": _profile(flow.calls[0]) if flow.calls else None,
           "final_profile": _profile(next((c for c in reversed(flow.calls) if c["role"] != "review"), None)),
           "wall_s": round(clock() - t0, 3)}
    flow.emit({"event": "done", "status": out["status"], "exit_code": out["exit_code"], "level": sp.level,
               "escalations": flow.esc, "usage": out["usage"], "wall_s": out["wall_s"]})
    return out

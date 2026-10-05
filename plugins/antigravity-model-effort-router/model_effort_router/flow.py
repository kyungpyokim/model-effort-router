"""mer run flow (spec 3.4): implement session -> Test Gate -> cascade escalation -> independent review.

All I/O is injected (runner, gate_fn, diff_fn, emit) so the flow is testable without codex or git.
The host (codex or claude, host/hosts.py) supplies the argv builders, stream parser and effort mapping.
"""
import time

from . import review as rv
from .difficulty.decision import merge_risk_flags
from .difficulty.risk import detect_risk_flags
from .host.hosts import CODEX
from .policy.session import ONE_WAY_FLAGS, REVIEW_DEFAULT

GATE_TEXT_MAX = 2000
USAGE_KEYS = ("input", "cached_input", "output", "reasoning_output")
PLAN_FIRST = "First write a short plan, then implement it. "
WRAP_UP = "When finished, end with a short summary of the changes."
SUBAGENT_HINT = ("Use a subagent only when independent exploration materially improves the result; never to "
                 "parallelise code search, test runs or repeated checks. ")  # when subagents are enabled (L5)
# when subagents are disabled, the session checks its own work (measurement B, plan 22.3)
SELF_CHECK = ("Make every new test fail on the code before your change (force the race or failure it guards "
              "against), and validate inputs before changing any state. ")


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


def _changed_paths(diff):
    return [*(diff.get("files") or []), *(diff.get("untracked") or [])] if diff.get("is_repo") else []


def _change_summary(paths, flags):
    """Door and blast radius for the human reviewer (None: no repo or no change)."""
    if not paths:
        return None
    return {"files": len(paths), "top_dirs": len({p.split("/", 1)[0] for p in paths}),
            "door": "one-way" if set(flags) & set(ONE_WAY_FLAGS) else "two-way"}


def _profile(call):
    return {k: call[k] for k in ("tier", "model", "requested_effort", "applied_effort")} if call else None


class _Flow:
    def __init__(self, request, sp, cwd, runner, env, gate_fn, diff_fn, emit, max_esc, timeout_s, config, clock, host):
        self.host, self.cx = host, host.exec
        self.request, self.sp, self.cwd, self.runner = request, sp, cwd, runner
        self.env, self.gate_fn, self.diff_fn, self.emit = self.cx.session_env(env), gate_fn, diff_fn, emit
        self.max_esc, self.timeout_s, self.config, self.clock = max_esc, timeout_s, config, clock
        self.calls, self.tracker = [], self.cx.UsageTracker()
        self.thread, self.esc, self.profile, self.message = None, 0, sp.start, None
        self.gate = None
        self.review = {"verdict": None, "findings": None, "skipped": "not required"}
        self.review_required = bool(sp.review)

    def call(self, role, argv, profile, thread=None, subagents=None):
        t0, r = self.clock(), self.host.resolve(profile, self.config)
        rec = {"role": role, "thread_id": thread, "tier": profile.tier, "model": r.model,
               "requested_effort": r.requested_effort, "applied_effort": r.applied_effort, "subagents": subagents,
               "usage": None}
        self.calls.append(rec)  # before running: a timed-out call still shows up (usage None = missing)
        try:
            stream = self.cx.parse_stream(self.runner(argv, cwd=self.cwd, env=self.env, timeout_s=self.timeout_s))
        finally:
            rec["wall_s"] = round(self.clock() - t0, 3)
        tid = stream.thread_id or thread
        # no thread id: a fresh session's cumulative usage is its own (never share a tracker slot)
        rec.update(thread_id=tid, usage=self.tracker.delta(tid, stream.usage) if tid else stream.usage)
        if getattr(stream, "extra", None):  # host-reported cost / per-model usage: a cross-check, never required
            rec.update(host_reported=stream.extra)
        if thread and tid:
            self.thread = tid  # a resume may answer with another id (claude --resume): follow it
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
        n = self.sp.implement_subagents
        stream, rec = self.call("escalate", self.cx.resume_argv(profile, self.thread, text, self.config, n), profile, self.thread, n)
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
        n = self.sp.review_subagents
        stream, rec = self.call("review", self.cx.session_argv(profile, prompt, "read-only", self.config, n), profile, subagents=n)
        self.emit({"event": "session_start", **rec})
        verdict, findings = rv.parse_verdict(stream.text)
        self.review = {"verdict": verdict, "findings": findings, "skipped": None, "text": stream.text or ""}
        self.emit({"event": "review", "verdict": verdict, "findings": findings, "thread_id": rec["thread_id"],
                   "usage": rec["usage"]})
        return True

    def _clean(self):
        d = self.diff_fn(self.cwd)
        return bool(d.get("is_repo")) and not d.get("diff") and not d.get("untracked")

    def nudge_if_unchanged(self, was_clean):
        """A route request must change files. Measurement B' (plan 22.3): a session answered "changed" without a
        single tool call and the unchanged tests passed. Checked only on a tree that was clean before (a dirty tree's
        edits to already-changed files are not visible). One nudge in the same session; still nothing -> False."""
        if not was_clean or not self.thread or not self._clean():
            return True
        n = self.sp.implement_subagents
        text = "No file in the workspace was changed. Make the requested change now by editing the files, then stop."
        stream, rec = self.call("nudge", self.cx.resume_argv(self.profile, self.thread, text, self.config, n),
                                self.profile, self.thread, n)
        self.message = stream.text or self.message
        self.emit({"event": "nudge", **rec})
        return not self._clean()

    def implement(self):
        sp = self.sp
        n = sp.implement_subagents
        was_clean = self._clean()
        prompt = f"{self.request}\n\n{PLAN_FIRST if sp.plan_first else ''}{SUBAGENT_HINT if n else ''}{SELF_CHECK if n == 0 else ''}{WRAP_UP}"
        stream, rec = self.call("implement", self.cx.session_argv(sp.start, prompt, "workspace-write", self.config, n), sp.start,
                                subagents=n)
        self.thread, self.message = rec["thread_id"], stream.text
        self.emit({"event": "session_start", **rec})
        if not self.nudge_if_unchanged(was_clean):
            return {"status": "no_changes", "exit_code": 1, "message": self.message}
        gate = self.gate_loop()
        if sp.review and gate["overall"] == "failed":
            self.review["skipped"] = "gate failed"
        elif sp.review and self.run_review(sp.review) and self.review["verdict"] == "changes_requested" and self.thread:
            self.apply_review()
        return self.outcome()

    def apply_review(self):
        """One fix turn in the implement session at its current profile, then the gate; no re-review (pilot v4:
        reviews found real defects that a report-only run left unfixed; a re-review loop doubled the cost)."""
        text = ("An independent review requested changes. Address these findings yourself in this session (do not "
                "spawn subagents), then stop.\n\n"
                f"{self.review['text'][-rv.FINDINGS_MAX:]}")
        # the fix is applied in this session, as its text says: no subagents even at L5 ("codex" policy: no flags)
        n = None if self.sp.implement_subagents is None else 0
        stream, rec = self.call("review_fix", self.cx.resume_argv(self.profile, self.thread, text, self.config, n),
                                self.profile, self.thread, n)
        self.message = stream.text or self.message
        self.emit({"event": "review_fix", **rec})
        self.review = {**self.review, "fixed": True}
        self.run_gate()

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
        stream, rec = self.call("plan", self.cx.session_argv(self.sp.plan_profile, prompt, "read-only", self.config),
                                self.sp.plan_profile)
        self.emit({"event": "session_start", **rec})
        return {"status": "ok", "exit_code": 0, "message": stream.text}

    def outcome(self):
        if self.gate and self.gate["overall"] == "failed":
            status = "gate_failed"
        elif self.review["verdict"] == "changes_requested":
            status = "review_fixed" if self.review.get("fixed") else "changes_requested"
        elif self.review_required and self.review["verdict"] != "approved":  # a required review never passes silently
            status = "review_skipped" if self.review["skipped"] else "review_unknown"
        else:
            status = "ok"
        return {"status": status, "exit_code": 0 if status in ("ok", "review_fixed") else 1, "message": self.message}


def run_flow(request, sp, *, cwd, runner, env, gate_fn, diff_fn, emit, target="route", max_escalations=2,
             timeout_s=1200, config=None, clock=time.monotonic, host=CODEX, risk_flags=()):
    """`risk_flags`: the route's flags; the result adds those of the final diff's paths."""
    flow = _Flow(request, sp, cwd, runner, env, gate_fn, diff_fn, emit, max_escalations, timeout_s,
                 config or host.config, clock, host)
    t0 = clock()
    try:
        result = getattr(flow, {"plan_only": "plan_only", "review_only": "review_only"}.get(target, "implement"))()
    except Exception as exc:  # timeout, codex crash: report, never traceback
        result = {"status": "error", "exit_code": 1, "error": f"{type(exc).__name__}: {exc}"[:300],
                  "message": flow.message}
    paths = [] if target == "plan_only" else _changed_paths(flow.diff_fn(cwd))
    # ponytail: path-based flags only (diff text would flag "lock"/"charge" everywhere); content scan if paths miss real cases
    flags = merge_risk_flags(risk_flags, detect_risk_flags("", paths))
    review = {**flow.review, **({"text": flow.review["text"][-rv.FINDINGS_MAX:]} if "text" in flow.review else {})}
    out = {**result, "level": sp.level, "target": target, "escalations": flow.esc, "gate": (flow.gate or {}).get("overall"),
           "review": review, "risk_flags": list(flags),
           "change": _change_summary(paths, flags), "calls": flow.calls, "usage": _sum_usage(flow.calls),
           "threads": list(dict.fromkeys(c["thread_id"] for c in flow.calls if c["thread_id"])),
           "profile": _profile(flow.calls[0]) if flow.calls else None,
           "final_profile": _profile(next((c for c in reversed(flow.calls) if c["role"] != "review"), None)),
           "wall_s": round(clock() - t0, 3)}
    flow.emit({"event": "done", "status": out["status"], "exit_code": out["exit_code"], "level": sp.level,
               "escalations": flow.esc, "usage": out["usage"], "wall_s": out["wall_s"]})
    return out

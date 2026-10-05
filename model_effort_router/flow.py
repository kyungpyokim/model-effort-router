"""mer run flow (spec 3.4): implement session -> Test Gate -> cascade escalation -> independent review.

All I/O is injected (runner, gate_fn, diff_fn, emit) so the flow is testable without codex or git.
The host (codex or claude, host/hosts.py) supplies the argv builders, stream parser and effort mapping.
"""
import os
import time

from . import review as rv
from .difficulty.decision import merge_risk_flags
from .difficulty.risk import detect_content_flags, detect_risk_flags
from .gate import probe as pb
from .gate.discovery import Check
from .gate.run import DEFAULT_TIMEOUT_S as PROBE_TIMEOUT_S  # the probe runs the gate's test command: same limit
from .host.hosts import CODEX
from .policy.session import ONE_WAY_FLAGS, REVIEW_DEFAULT

GATE_TEXT_MAX = 2000
CONTENT_SCAN_MAX = 64_000  # chars read from a new untracked file for the content flags
PROSE_SUFFIXES = (".md", ".rst", ".txt")
USAGE_KEYS = ("input", "cached_input", "output", "reasoning_output")
PLAN_FIRST = "First write a short plan, then implement it. "
WRAP_UP = "When finished, end with a short summary of the changes."
SUBAGENT_HINT = ("Use a subagent only when independent exploration materially improves the result; never to "
                 "parallelise code search, test runs or repeated checks. ")  # when subagents are enabled (L5)
PROBE_NUDGE = ("The Test Gate passed, but the tests you added or changed also pass on the code before your change, so "
               "they do not guard it. If the request is a behaviour change or a bug fix, make each new test fail on "
               "the old code (force the failure it guards against) without changing product behaviour beyond the "
               "request. If the tests intentionally cover behaviour that already worked, change nothing and say so "
               "in one sentence. Then stop.")
NUDGE_REPLY_MAX = 300
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


def _stamp(cwd, path):
    """Size and mtime, to tell a file the run edited from one that merely was already changed (None: gone)."""
    try:
        st = os.stat(os.path.join(cwd, path))
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def _changed_since(before, after):
    """Paths whose stamp differs between two snapshots; a path gone from either side has stamp None."""
    return sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))


def _added_text(cwd, diff, paths):
    """What this run wrote into `paths`, for the content flags: added diff lines, and new untracked files read from
    disk (capped). Prose is skipped: docs name "drop table" without running it."""
    paths = {p for p in paths if not p.endswith(PROSE_SUFFIXES)}
    out, mine = [], False
    for line in (diff.get("diff") or "").splitlines():
        if line.startswith("+++ "):
            mine = line[6:] in paths  # "+++ b/<path>"; a quoted name never matches, so it is not scanned
        elif mine and line.startswith("+"):
            out.append(line[1:])
    for path in paths & set(diff.get("untracked") or ()):
        try:
            with open(os.path.join(cwd, path), errors="replace") as f:
                out.append(f.read(CONTENT_SCAN_MAX))
        except OSError:
            pass
    return "\n".join(out)


def _change_summary(paths, flags):
    """Door and blast radius for the human reviewer (None: no repo or no change)."""
    if not paths:
        return None
    return {"files": len(paths), "top_dirs": len({p.split("/", 1)[0] for p in paths}),
            "door": "one-way" if set(flags) & set(ONE_WAY_FLAGS) else "two-way"}


def _profile(call):
    return {k: call[k] for k in ("tier", "model", "requested_effort", "applied_effort")} if call else None


class _Flow:
    def __init__(self, request, sp, cwd, runner, env, gate_fn, diff_fn, emit, max_esc, timeout_s, config, clock, host,
                 probe_nudge=False):
        self.host, self.cx, self.probe_nudge_on = host, host.exec, probe_nudge
        self.request, self.sp, self.cwd, self.runner = request, sp, cwd, runner
        self.env, self.gate_fn, self.diff_fn, self.emit = self.cx.session_env(env), gate_fn, diff_fn, emit
        self.max_esc, self.timeout_s, self.config, self.clock = max_esc, timeout_s, config, clock
        self.calls, self.tracker = [], self.cx.UsageTracker()
        self.thread, self.esc, self.profile, self.message = None, 0, sp.start, None
        self.gate = None
        self.probe = None  # test-without-change probe result; None until implement() has a passing gate
        self.review = {"verdict": None, "findings": None, "skipped": "not required"}
        # path -> stamp of what was already changed before implement(); review_only keeps it empty. The reviewer still
        # sees the full diff, the summary only this run's change.
        self.baseline = {}
        self.head = None
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

    def run_probe(self):
        """Report whether the tests this run changed also pass on the pre-change code. Never changes the outcome."""
        self.probe = self._probe()
        if self.probe["verdict"] != "skipped":  # a skipped probe ran nothing: no event
            self.emit({"event": "probe", **{k: v for k, v in self.probe.items() if k != "output_tail"}})  # test output stays out of the log

    def _probe(self):
        test = (self.gate.get("checks") or {}).get("test") or {}
        if self.baseline:  # HEAD would wipe the user's earlier uncommitted work and fail for the wrong reason
            return pb.result("skipped", "the tree was not clean before the run")
        if self.gate["overall"] == "failed" or test.get("status") != "passed":  # lint etc. not_run is fine
            return pb.result("skipped", "the test gate did not pass")
        try:
            if rv.git_head(self.cwd) != self.head:  # read-only git call, deliberately not routed through diff_fn
                return pb.result("skipped", "HEAD moved during the run")
            diff = self.diff_fn(self.cwd)
            if not diff.get("is_repo"):
                return pb.result("skipped", "not a git repository")
            command, source = test.get("command"), test.get("source")
            check = Check("test", command, source, source == "config") if command else None
            return pb.probe_without_change(self.cwd, _changed_paths(diff), check, PROBE_TIMEOUT_S)
        except Exception as exc:  # like a broken gate: inconclusive, never a failed run
            return pb.result("inconclusive", f"{type(exc).__name__}: {exc}"[:300])

    def probe_nudge(self):
        """The probe says the tests pass on the old code: one turn in the implement session. A turn that changed no
        file is the agent saying the tests are intended; only a change re-runs the gate and the probe. Report-only:
        status and exit code stay with the gate, and a failing nudge is recorded, never an error for the run."""
        first = self.probe["verdict"]
        try:
            nudge = self._nudge_turn(first)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:300]
            self.emit({"event": "probe_nudge", "error": error})
            self.run_gate()  # the failed turn may have edited files: the gate must describe the final tree
            self.run_probe()  # no escalation: the session is not reliable after a failed turn
            nudge = {"first": first, "error": error}
        self.probe = {**self.probe, "nudge": nudge}

    def _nudge_turn(self, first):
        before = self._stamps()
        n = None if self.sp.implement_subagents is None else 0  # one turn: no subagents, as in apply_review
        stream, rec = self.call("probe_nudge", self.cx.resume_argv(self.profile, self.thread, PROBE_NUDGE, self.config, n),
                                self.profile, self.thread, n)
        self.emit({"event": "probe_nudge", **rec})
        turn_changed = _changed_since(before, self._stamps())
        product = []
        if turn_changed:
            self.gate_loop()
            self.run_probe()
            # against the final tree: an escalation after the nudge may rewrite product code too; docs are neutral
            product = [p for p in _changed_since(before, self._stamps())
                       if not pb.is_test_side(p) and not p.endswith(PROSE_SUFFIXES)]
        return {"first": first, "reply": (stream.text or "")[:NUDGE_REPLY_MAX], "changed": bool(turn_changed),
                "product_paths_added": product}

    def _stamps(self):
        return {p: _stamp(self.cwd, p) for p in _changed_paths(self.diff_fn(self.cwd))}

    def run_review(self, profile):
        diff = self.diff_fn(self.cwd)
        if not diff.get("is_repo"):
            self.review = {"verdict": None, "findings": None, "skipped": "not a git repository"}
            return False
        prompt = rv.review_prompt(self.request, diff, self.gate, self.probe)
        n = self.sp.review_subagents
        stream, rec = self.call("review", self.cx.session_argv(profile, prompt, "read-only", self.config, n), profile, subagents=n)
        self.emit({"event": "session_start", **rec})
        verdict, findings = rv.parse_verdict(stream.text)
        self.review = {"verdict": verdict, "findings": findings, "skipped": None, "text": stream.text or ""}
        self.emit({"event": "review", "verdict": verdict, "findings": findings, "thread_id": rec["thread_id"],
                   "usage": rec["usage"]})
        return True

    def _clean(self, d=None):
        d = d or self.diff_fn(self.cwd)
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
        before = self.diff_fn(self.cwd)
        was_clean = self._clean(before)
        self.baseline = {p: _stamp(self.cwd, p) for p in _changed_paths(before)}
        self.head = rv.git_head(self.cwd)  # the probe snapshots HEAD: a commit during the run invalidates it
        prompt = f"{self.request}\n\n{PLAN_FIRST if sp.plan_first else ''}{SUBAGENT_HINT if n else ''}{SELF_CHECK if n == 0 else ''}{WRAP_UP}"
        stream, rec = self.call("implement", self.cx.session_argv(sp.start, prompt, "workspace-write", self.config, n), sp.start,
                                subagents=n)
        self.thread, self.message = rec["thread_id"], stream.text
        self.emit({"event": "session_start", **rec})
        if not self.nudge_if_unchanged(was_clean):
            return {"status": "no_changes", "exit_code": 1, "message": self.message}
        self.gate_loop()
        self.run_probe()
        if self.probe_nudge_on and self.thread and self.probe["verdict"] == "passes_without_change":
            self.probe_nudge()
        if sp.review and self.gate["overall"] == "failed":
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
             timeout_s=1200, config=None, clock=time.monotonic, host=CODEX, risk_flags=(), probe_nudge=False):
    """`risk_flags`: the route's flags; the result adds those of the final diff's paths. `probe_nudge`: gate.probe_nudge."""
    flow = _Flow(request, sp, cwd, runner, env, gate_fn, diff_fn, emit, max_escalations, timeout_s,
                 config or host.config, clock, host, probe_nudge)
    t0 = clock()
    try:
        result = getattr(flow, {"plan_only": "plan_only", "review_only": "review_only"}.get(target, "implement"))()
    except Exception as exc:  # timeout, codex crash: report, never traceback
        result = {"status": "error", "exit_code": 1, "error": f"{type(exc).__name__}: {exc}"[:300],
                  "message": flow.message}
    final = {} if target == "plan_only" else flow.diff_fn(cwd)
    paths = [p for p in _changed_paths(final) if p not in flow.baseline or _stamp(cwd, p) != flow.baseline[p]]
    # request words match paths only; in code just destructive statements count ("lock"/"charge" are everywhere)
    flags = merge_risk_flags(risk_flags, detect_risk_flags("", paths), detect_content_flags(_added_text(cwd, final, paths)))
    review = {**flow.review, **({"text": flow.review["text"][-rv.FINDINGS_MAX:]} if "text" in flow.review else {})}
    out = {**result, "level": sp.level, "target": target, "escalations": flow.esc, "gate": (flow.gate or {}).get("overall"),
           "review": review, "probe": flow.probe, "risk_flags": list(flags),
           "change": _change_summary(paths, flags), "calls": flow.calls, "usage": _sum_usage(flow.calls),
           "threads": list(dict.fromkeys(c["thread_id"] for c in flow.calls if c["thread_id"])),
           "profile": _profile(flow.calls[0]) if flow.calls else None,
           "final_profile": _profile(next((c for c in reversed(flow.calls) if c["role"] != "review"), None)),
           "wall_s": round(clock() - t0, 3)}
    flow.emit({"event": "done", "status": out["status"], "exit_code": out["exit_code"], "level": sp.level,
               "escalations": flow.esc, "usage": out["usage"], "wall_s": out["wall_s"]})
    return out

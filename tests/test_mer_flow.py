import json
import unittest

from model_effort_router import review as rv
from model_effort_router.difficulty.decision import DifficultyDecision
from model_effort_router.flow import run_flow
from model_effort_router.host import codex_exec as cx
from model_effort_router.policy.session import session_plan

REQ = "Fix the discount bug in shop/pricing.py"


def stream(thread, text="done", i=100, c=50, o=10):
    ev = [{"type": "thread.started", "thread_id": thread},
          {"type": "item.completed", "item": {"type": "agent_message", "text": text}},
          {"type": "turn.completed", "usage": {"input_tokens": i, "cached_input_tokens": c, "output_tokens": o,
                                               "reasoning_output_tokens": 0}}]
    return "\n".join(map(json.dumps, ev))


def splan(level, flags=(), overrides=None, policy="level"):
    return session_plan(DifficultyDecision(level, "fake", risk_flags=flags), flags, overrides, policy)


GATE_OK = {"overall": "passed", "checks": {"test": {"status": "passed"}}}
GATE_BAD = {"overall": "failed", "checks": {"test": {"status": "failed", "command": "python3 -m unittest",
                                                    "output_tail": "AssertionError: 3 != 4"}}}
GATE_NR = {"overall": "incomplete", "checks": {"test": {"status": "not_run", "reason": "no command discovered"}}}
REPO = {"is_repo": True, "diff": "diff --git a/x b/x\n+new line\n", "files": ["x"], "untracked": ["new.py"]}
CLEAN = {"is_repo": True, "diff": "", "files": [], "untracked": []}


class Harness:
    """Scripted runner: answers by argv shape; records every call."""

    def __init__(self, gates=(GATE_OK,), verdicts=(), diff=REPO, impl_text="implemented", changes_after=1):
        self.calls, self.events = [], []
        self.gates, self.verdicts, self.diff, self.impl_text = list(gates), list(verdicts), diff, impl_text
        self.changes_after = changes_after  # codex calls before the tree shows `diff` (clean until then); None: never
        self.impl_i, self.fail_on = 0, None

    def runner(self, argv, *, cwd, env, timeout_s):
        self.calls.append({"argv": argv, "cwd": cwd, "env": env, "timeout_s": timeout_s})
        if self.fail_on == len(self.calls):
            raise TimeoutError("slow")
        if "read-only" in argv:
            if "VERDICT" not in argv[-1]:  # plan_only session
                return stream("T-plan", "1. do a\n2. do b")
            n = sum("read-only" in c["argv"] for c in self.calls)
            v = self.verdicts.pop(0) if self.verdicts else ("approved", 0)
            return stream(f"T-rev{n}", f"looks ok\nVERDICT: {v[0]}\nFINDINGS: {v[1]}", i=500, c=0, o=20)
        self.impl_i += 1  # cumulative usage like a real resumed session
        return stream("T-impl", self.impl_text, i=100 * self.impl_i * self.impl_i, c=10 * self.impl_i, o=10 * self.impl_i)

    def diff_fn(self, cwd):
        if not self.diff.get("is_repo"):
            return self.diff
        changed = self.changes_after is not None and len(self.calls) >= self.changes_after
        return self.diff if changed else CLEAN

    def gate(self, cwd):
        return self.gates.pop(0) if len(self.gates) > 1 else self.gates[0]

    def run(self, level="L2", flags=(), request=REQ, **kw):
        kw.setdefault("target", "route")
        return run_flow(request, splan(level, flags, kw.pop("overrides", None), kw.pop("policy", "level")), cwd="/w", runner=self.runner,
                        env={"A": "1"}, gate_fn=self.gate, diff_fn=self.diff_fn, emit=self.events.append,
                        **kw)

    def kinds(self):
        return [e["event"] for e in self.events]


class NoChangeTest(unittest.TestCase):
    """Measurement B' (plan 22.3): a session claimed a change without touching a file."""

    def test_unchanged_tree_gets_one_nudge_then_continues(self):
        h = Harness(changes_after=2)
        r = h.run("L2")
        self.assertEqual([c["role"] for c in r["calls"]], ["implement", "nudge"])
        self.assertIn(h.calls[0]["argv"][-1].split("\n")[0], REQ)
        self.assertIn("resume", h.calls[1]["argv"])
        self.assertIn("No file in the workspace was changed", h.calls[1]["argv"][-1])
        self.assertIn("agents.enabled=false", h.calls[1]["argv"])  # same subagent policy as the implement session
        self.assertEqual((r["status"], r["exit_code"], r["gate"]), ("ok", 0, "passed"))
        self.assertIn("nudge", h.kinds())

    def test_still_unchanged_after_the_nudge_is_no_changes_without_gate_or_review(self):
        h = Harness(changes_after=None)
        r = h.run("L4")
        self.assertEqual([c["role"] for c in r["calls"]], ["implement", "nudge"])
        self.assertEqual((r["status"], r["exit_code"], r["gate"]), ("no_changes", 1, None))

    def test_changed_tree_and_dirty_or_non_repo_trees_are_not_nudged(self):
        self.assertEqual([c["role"] for c in Harness().run("L2")["calls"]], ["implement"])
        dirty = Harness(changes_after=0)  # dirty before the session: edits may be invisible, never nudge
        dirty.diff_fn = lambda cwd: REPO
        self.assertEqual([c["role"] for c in dirty.run("L2")["calls"]], ["implement"])
        self.assertEqual([c["role"] for c in Harness(diff={"is_repo": False}).run("L2")["calls"]], ["implement"])


class ImplementTest(unittest.TestCase):
    def test_first_command_and_env(self):
        h = Harness()
        r = h.run("L2")
        argv = h.calls[0]["argv"]
        self.assertEqual(argv[:6], ["codex", "exec", "--json", "--skip-git-repo-check", "-s", "workspace-write"])
        self.assertEqual(argv[argv.index("-m") + 1], "gpt-6-luna")
        self.assertIn("model_reasoning_effort=medium", argv)
        self.assertTrue(argv[-1].startswith(REQ))
        self.assertIn("summary", argv[-1])
        self.assertNotIn("short plan", argv[-1].lower())  # L2: no plan-first instruction
        self.assertEqual((h.calls[0]["env"]["MER_CLASSIFIER"], h.calls[0]["env"]["A"], h.calls[0]["cwd"]), ("1", "1", "/w"))
        self.assertEqual((r["exit_code"], r["status"], r["escalations"], r["gate"]), (0, "ok", 0, "passed"))
        self.assertEqual(r["message"], "implemented")
        self.assertEqual(h.kinds(), ["session_start", "gate", "done"])

    def test_plan_first_instruction_for_l4_and_risk_but_not_l3(self):
        for level, flags, expected in (("L3", (), False), ("L4", (), True), ("L1", ("auth",), True)):
            h = Harness(verdicts=[("approved", 0)])
            h.run(level, flags)
            self.assertEqual("short plan" in h.calls[0]["argv"][-1].lower(), expected, level)

    def test_requested_vs_applied_effort_recorded(self):
        h = Harness()
        h.run("L5")
        start = h.events[0]
        self.assertEqual((start["role"], start["model"], start["requested_effort"], start["applied_effort"]),
                         ("implement", "gpt-6.1-sol", "xhigh", "xhigh"))
        self.assertEqual(start["thread_id"], "T-impl")

    def test_usage_delta_per_call_is_not_cumulative_sum(self):
        h = Harness(gates=(GATE_BAD, GATE_BAD, GATE_OK))
        r = h.run("L2")
        # cumulative input 100, 400, 900 -> deltas 100, 300, 500
        self.assertEqual([c["usage"]["input"] for c in r["calls"]], [100, 300, 500])
        self.assertEqual(r["usage"]["input"], 900)
        self.assertEqual(r["usage"]["total"], 900 + 30)

    def test_runner_failure_is_error_result_with_done_event(self):
        h = Harness()
        h.fail_on = 1
        r = h.run("L2")
        self.assertEqual((r["exit_code"], r["status"]), (1, "error"))
        self.assertIn("TimeoutError", r["error"])
        self.assertEqual(h.kinds()[-1], "done")
        self.assertEqual([(c["role"], c["usage"]) for c in r["calls"]], [("implement", None)])  # kept, counted missing
        self.assertEqual(r["usage"]["missing"], 1)


class EscalationTest(unittest.TestCase):
    def test_gate_failure_resumes_same_session_at_next_rung(self):
        h = Harness(gates=(GATE_BAD, GATE_OK))
        r = h.run("L2")
        argv = h.calls[1]["argv"]
        self.assertEqual(argv[:6], ["codex", "exec", "resume", "--json", "--skip-git-repo-check", "-m"])
        self.assertEqual((argv[6], argv[argv.index("-c") + 1]), ("gpt-6-luna", "model_reasoning_effort=high"))
        self.assertEqual(argv[-2], "T-impl")
        self.assertIn('sandbox_mode="workspace-write"', argv)  # resume has no -s; escalated rungs must still edit
        self.assertIn("AssertionError: 3 != 4", argv[-1])
        self.assertEqual((r["exit_code"], r["escalations"]), (0, 1))
        self.assertEqual(h.kinds(), ["session_start", "gate", "escalate", "gate", "done"])
        esc = h.events[2]
        self.assertEqual((esc["reason"], esc["thread_id"], esc["tier"], esc["applied_effort"]), ("gate_failed", "T-impl", "balanced", "high"))

    def test_second_escalation_uses_frontier_and_budget_caps_at_max(self):
        h = Harness(gates=(GATE_BAD,))
        r = h.run("L2")
        models = [c["argv"][c["argv"].index("-m") + 1] for c in h.calls]
        self.assertEqual(models, ["gpt-6-luna", "gpt-6-luna", "gpt-6.1-sol"])
        self.assertEqual((r["exit_code"], r["status"], r["escalations"]), (1, "gate_failed", 2))

    def test_max_escalations_option(self):
        h = Harness(gates=(GATE_BAD,))
        self.assertEqual(h.run("L2", max_escalations=1)["escalations"], 1)
        h = Harness(gates=(GATE_BAD,))
        r = h.run("L2", max_escalations=0)
        self.assertEqual((len(h.calls), r["status"]), (1, "gate_failed"))

    def test_ladder_end_stops_and_reports(self):
        h = Harness(gates=(GATE_BAD,))
        r = h.run("L5")
        self.assertEqual((len(h.calls), r["exit_code"], r["escalations"]), (1, 1, 0))
        h = Harness(gates=(GATE_BAD,))
        self.assertEqual(h.run("L4")["escalations"], 1)  # one rung, then stop

    def test_not_run_never_escalates(self):
        h = Harness(gates=(GATE_NR,))
        r = h.run("L2")
        self.assertEqual((len(h.calls), r["exit_code"], r["gate"]), (1, 0, "incomplete"))

    def test_no_thread_id_cannot_resume(self):
        h = Harness(gates=(GATE_BAD,))
        h.runner = lambda argv, **k: "{}"
        r = h.run("L2")
        self.assertEqual((r["exit_code"], r["escalations"]), (1, 0))

    def test_calls_without_thread_id_keep_their_own_usage(self):
        def no_thread(argv, **k):
            body = stream("x", "VERDICT: approved\nFINDINGS: 0", i=60 if "read-only" in argv else 100)
            return "\n".join(line for line in body.splitlines() if "thread.started" not in line)
        h = Harness()
        h.runner = no_thread
        r = h.run("L4")
        self.assertEqual([c["usage"]["input"] for c in r["calls"]], [100, 60])  # review not diffed against implement
        self.assertEqual(r["usage"]["input"], 160)

    def test_override_start_profile_used(self):
        from model_effort_router.profiles.profiles import Profile
        h = Harness()
        h.run("L2", overrides={"session": Profile("frontier", "high")})
        self.assertEqual(h.calls[0]["argv"][h.calls[0]["argv"].index("-m") + 1], "gpt-6.1-sol")


class ReviewTest(unittest.TestCase):
    def test_independent_review_new_read_only_session_with_diff_and_gate(self):
        h = Harness()
        r = h.run("L4")
        rev = h.calls[1]["argv"]
        self.assertIn("read-only", rev)
        self.assertNotIn("resume", rev)
        self.assertEqual(rev[rev.index("-m") + 1], "gpt-6.1-sol")
        self.assertIn("model_reasoning_effort=high", rev)
        for needle in (REQ, "+new line", '"overall": "passed"', "VERDICT: approved|changes_requested", "FINDINGS: <n>"):
            self.assertIn(needle, rev[-1])
        self.assertNotIn("implemented", rev[-1])  # no implement-session transcript
        self.assertEqual((r["review"]["verdict"], r["review"]["findings"], r["exit_code"]), ("approved", 0, 0))
        self.assertEqual(h.kinds(), ["session_start", "gate", "session_start", "review", "done"])
        self.assertEqual(h.events[3]["thread_id"], "T-rev1")

    def test_auth_flag_adds_review_below_l4(self):
        h = Harness()
        r = h.run("L3", ("auth",))
        self.assertEqual((len(h.calls), r["review"]["verdict"]), (2, "approved"))

    def test_review_prompt_forbids_subagents(self):
        # pilot v4: the review session spawned its own code-reviewer subagent (~0.2M tokens) per global instructions
        self.assertIn("do not spawn subagents", rv.review_prompt("req", REPO, GATE_OK))

    def test_risk_flag_alone_adds_no_review_below_l4(self):
        h = Harness()
        r = h.run("L1", ("payment",))
        self.assertEqual((len(h.calls), r["review"]["skipped"]), (1, "not required"))

    def test_data_loss_below_l4_gets_a_review_when_subagents_are_off(self):
        h = Harness()
        r = h.run("L1", ("data_loss",))
        self.assertEqual([c["role"] for c in r["calls"]], ["implement", "review"])

    def test_risk_flag_raises_l4_review_to_its_floor(self):
        h = Harness()
        h.run("L4", ("data_loss",))
        self.assertIn("model_reasoning_effort=xhigh", h.calls[-1]["argv"])

    def test_changes_requested_gets_one_fix_turn_in_the_same_session_and_no_re_review(self):
        for level, flags in (("L4", ()), ("L4", ("auth",)), ("L5", ())):
            h = Harness(verdicts=[("changes_requested", 2)])
            r = h.run(level, flags)
            fix = h.calls[2]["argv"]
            self.assertEqual((len(h.calls), r["escalations"], r["exit_code"], r["status"]), (3, 0, 0, "review_fixed"))
            self.assertIn("resume", fix)
            self.assertEqual(fix[-2], "T-impl")  # same implement session, not a new one
            self.assertIn("looks ok", fix[-1])  # the review findings are handed over
            self.assertIn("do not spawn subagents", fix[-1])  # pilot: the fix turn spawned a reviewer subagent
            self.assertEqual(h.calls[2]["argv"][h.calls[2]["argv"].index("-m") + 1],
                             h.calls[0]["argv"][h.calls[0]["argv"].index("-m") + 1])  # current profile, no escalation
            self.assertEqual((h.kinds().count("gate"), h.kinds().count("review"), r["review"]["fixed"]), (2, 1, True))

    def test_gate_failing_after_the_review_fix_fails_the_run(self):
        h = Harness(gates=(GATE_OK, GATE_BAD), verdicts=[("changes_requested", 1)])
        r = h.run("L4")
        self.assertEqual((r["status"], r["exit_code"], len(h.calls)), ("gate_failed", 1, 3))

    def test_no_thread_id_means_no_fix_turn(self):
        h = Harness(verdicts=[("changes_requested", 1)])
        orig = h.runner
        h.runner = lambda argv, **k: "\n".join(line for line in orig(argv, **k).splitlines() if "thread.started" not in line)
        r = h.run("L4")
        self.assertEqual((r["status"], r["exit_code"], len(h.calls)), ("changes_requested", 1, 2))

    def test_unknown_verdict_no_loop_but_fails_required_review(self):
        h = Harness()
        orig = h.runner
        def runner(argv, **k):
            if "read-only" not in argv:
                return orig(argv, **k)
            h.calls.append({"argv": argv})
            return stream("T-r", "no verdict here")
        h.runner = runner
        r = h.run("L4")
        self.assertEqual((r["review"]["verdict"], r["status"], r["exit_code"], len(h.calls)),
                         ("unknown", "review_unknown", 1, 2))
        self.assertEqual(h.events[-2]["verdict"], "unknown")

    def test_not_a_repo_skips_review_with_message(self):
        h = Harness(diff={"is_repo": False})
        r = h.run("L4")
        self.assertEqual(len(h.calls), 1)
        self.assertEqual(r["review"], {"verdict": None, "findings": None, "skipped": "not a git repository"})
        self.assertEqual((r["status"], r["exit_code"]), ("review_skipped", 1))  # required review never silent

    def test_oversized_diff_replaced_by_file_list(self):
        big = {"is_repo": True, "diff": "x" * (rv.DIFF_CAP + 1), "files": ["a.py", "b.py"], "untracked": ["n.py"]}
        h = Harness(diff=big)
        h.run("L4")
        prompt = h.calls[1]["argv"][-1]
        self.assertNotIn("x" * 100, prompt)
        for needle in ("a.py", "b.py", "n.py", "too large"):
            self.assertIn(needle, prompt)

    def test_review_skipped_when_gate_still_failing(self):
        h = Harness(gates=(GATE_BAD,))
        r = h.run("L5")
        self.assertEqual((len(h.calls), r["exit_code"], r["review"]["skipped"]), (1, 1, "gate failed"))


class TargetTest(unittest.TestCase):
    def test_plan_only_single_read_only_session_no_gate(self):
        h = Harness()
        r = h.run("L3", target="plan_only")
        argv = h.calls[0]["argv"]
        self.assertEqual((len(h.calls), "read-only" in argv, "workspace-write" in argv), (1, True, False))
        self.assertIn("plan", argv[-1].lower())
        self.assertEqual((r["exit_code"], r["message"], "gate" in h.kinds()), (0, "1. do a\n2. do b", False))

    def test_review_only_reviews_current_diff(self):
        h = Harness(verdicts=[("changes_requested", 3)])
        r = h.run("L2", target="review_only")
        self.assertEqual(len(h.calls), 1)
        self.assertIn("read-only", h.calls[0]["argv"])
        self.assertEqual((r["review"]["verdict"], r["exit_code"]), ("changes_requested", 1))

    def test_review_only_outside_repo_is_a_clear_failure(self):
        h = Harness(diff={"is_repo": False})
        r = h.run("L2", target="review_only")
        self.assertEqual((len(h.calls), r["exit_code"], r["status"]), (0, 2, "no_git_repo"))


class HelperTest(unittest.TestCase):
    def test_parse_verdict(self):
        self.assertEqual(rv.parse_verdict("x\nVERDICT: approved\nFINDINGS: 0"), ("approved", 0))
        self.assertEqual(rv.parse_verdict("verdict: Changes_Requested\nfindings: 4\n"), ("changes_requested", 4))
        self.assertEqual(rv.parse_verdict("VERDICT: maybe"), ("unknown", None))
        self.assertEqual(rv.parse_verdict(""), ("unknown", None))
        self.assertEqual(rv.parse_verdict("VERDICT: approved"), ("approved", None))
        self.assertEqual(rv.parse_verdict("VERDICT: changes_requested\nFINDINGS: 1\nVERDICT: approved\nFINDINGS: 0"),
                         ("approved", 0))  # last one wins

    def test_stream_parse_takes_last_cumulative_and_ignores_garbage(self):
        text = stream("T1", "a", i=10) + "\nnot json\n" + stream("T1", "b", i=30)
        r = cx.parse_stream(text)
        self.assertEqual((r.thread_id, r.text, r.usage["input"]), ("T1", "b", 30))
        self.assertEqual(cx.parse_stream("").thread_id, None)
        self.assertIsNone(cx.parse_stream("").usage)

    def test_tracker_delta_per_thread_never_negative(self):
        t = cx.UsageTracker()
        def u(i):
            return {"input": i, "cached_input": 0, "output": 0, "reasoning_output": 0}
        self.assertEqual(t.delta("a", u(10))["input"], 10)
        self.assertEqual(t.delta("a", u(25))["input"], 15)
        self.assertEqual(t.delta("b", u(7))["input"], 7)
        self.assertEqual(t.delta("a", u(5))["input"], 0)
        self.assertIsNone(t.delta("a", None))


if __name__ == "__main__":
    unittest.main()


class ChangeSummaryTest(unittest.TestCase):
    """Door / blast radius for the human reviewer (PR skill fields): request flags plus the final diff's path flags."""

    def test_plain_change_is_a_two_way_door(self):
        r = Harness().run("L2")
        self.assertEqual((r["risk_flags"], r["change"]), ([], {"files": 2, "top_dirs": 2, "door": "two-way"}))

    def test_migration_path_makes_a_one_way_door(self):
        diff = {**REPO, "files": ["app/db/migrations/0003_drop.sql", "app/models.py"], "untracked": []}
        r = Harness(diff=diff).run("L2")
        self.assertEqual((r["risk_flags"], r["change"]), (["data_migration"], {"files": 2, "top_dirs": 1, "door": "one-way"}))

    def test_request_flag_counts_even_when_paths_do_not_show_it(self):
        r = Harness().run("L2", risk_flags=("data_loss",))
        self.assertEqual((r["risk_flags"], r["change"]["door"]), (["data_loss"], "one-way"))

    def test_request_and_path_flags_merge_in_canonical_order(self):
        diff = {**REPO, "files": ["src/auth/login.py"], "untracked": []}
        r = Harness(diff=diff).run("L2", risk_flags=("concurrency",))
        self.assertEqual((r["risk_flags"], r["change"]["door"]), (["auth", "concurrency"], "two-way"))

    def test_no_change_summary_without_a_repo_or_for_plan_only(self):
        self.assertIsNone(Harness(diff={"is_repo": False}).run("L2")["change"])
        r = Harness().run("L2", target="plan_only", risk_flags=("auth",))
        self.assertEqual((r["change"], r["risk_flags"]), (None, ["auth"]))

import json
import os
import tempfile
import unittest
from unittest import mock

from model_effort_router import review as rv
from model_effort_router.difficulty.decision import DifficultyDecision
from model_effort_router.flow import run_flow
from model_effort_router.gate import probe as pb
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


class ContentFlagTest(unittest.TestCase):
    """Door from what the run wrote, not only from where: destructive statements outside a migration path."""

    @staticmethod
    def section(path, *added, removed=()):
        body = "".join(f"-{r}\n" for r in removed) + "".join(f"+{a}\n" for a in added)
        return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n{body}"

    def run_diff(self, diff, **kw):
        return Harness(diff={"is_repo": True, "untracked": [], **diff}).run("L2", **kw)

    def test_an_added_destructive_statement_is_a_one_way_door(self):
        d = self.section("app/db.py", 'cur.execute("DROP TABLE users")')
        r = self.run_diff({"diff": d, "files": ["app/db.py"]})
        self.assertEqual((r["risk_flags"], r["change"]["door"]), (["data_loss"], "one-way"))

    def test_a_removed_statement_does_not_flag(self):
        d = self.section("app/db.py", "pass", removed=['cur.execute("DROP TABLE users")'])
        r = self.run_diff({"diff": d, "files": ["app/db.py"]})
        self.assertEqual((r["risk_flags"], r["change"]["door"]), ([], "two-way"))

    def test_prose_is_not_scanned(self):
        d = self.section("docs/ops.md", "Never run DROP TABLE by hand.")
        r = self.run_diff({"diff": d, "files": ["docs/ops.md"]})
        self.assertEqual(r["risk_flags"], [])

    def test_a_diff_section_of_a_file_the_run_did_not_change_is_ignored(self):
        d = self.section("old.py", "DROP TABLE legacy") + self.section("app/x.py", "x = 1")
        r = self.run_diff({"diff": d, "files": ["app/x.py"]})
        self.assertEqual(r["risk_flags"], [])

    def test_a_new_untracked_file_is_read_from_disk(self):
        with tempfile.TemporaryDirectory() as cwd:
            with open(os.path.join(cwd, "reset.sql"), "w") as f:
                f.write("ALTER TABLE users ADD COLUMN age int;\n")
            h = Harness(diff={"is_repo": True, "diff": "", "files": [], "untracked": ["reset.sql"]})
            r = run_flow(REQ, splan("L2"), cwd=cwd, runner=h.runner, env={}, gate_fn=h.gate, diff_fn=h.diff_fn,
                         emit=h.events.append)
        self.assertEqual((r["risk_flags"], r["change"]["door"]), (["data_migration"], "one-way"))

    def test_request_path_and_content_flags_merge_in_canonical_order(self):
        d = self.section("src/auth/store.py", "os.system('rm -rf /data')")
        r = self.run_diff({"diff": d, "files": ["src/auth/store.py"]}, risk_flags=("concurrency",))
        self.assertEqual(r["risk_flags"], ["auth", "data_loss", "concurrency"])


class BaselineTest(unittest.TestCase):
    """The blast radius counts what this run changed, not files that were already dirty before it."""

    def test_files_dirty_before_the_run_are_not_counted(self):
        before = {"is_repo": True, "diff": "d", "files": ["old.py"], "untracked": [".omc/a", ".omc/b"]}
        after = {**before, "files": ["old.py", "new.py"], "untracked": [".omc/a", ".omc/b", "db/migrations/0001.sql"]}
        h = Harness()
        h.diff_fn = lambda cwd: after if h.calls else before
        r = h.run("L2")
        self.assertEqual((r["change"], r["risk_flags"]), ({"files": 2, "top_dirs": 2, "door": "one-way"}, ["data_migration"]))

    def test_a_dirty_file_the_run_edits_again_is_counted(self):
        with tempfile.TemporaryDirectory() as cwd:
            path = os.path.join(cwd, "migrations_0002_drop.sql")
            with open(path, "w") as f:
                f.write("draft")
            dirty = {"is_repo": True, "diff": "", "files": [], "untracked": ["migrations_0002_drop.sql"]}
            h = Harness(diff=dirty, changes_after=0)
            runner = h.runner

            def editing_runner(argv, **kw):
                with open(path, "w") as f:
                    f.write("finished and longer")
                return runner(argv, **kw)

            h.runner = editing_runner
            r = run_flow(REQ, splan("L2"), cwd=cwd, runner=h.runner, env={}, gate_fn=h.gate, diff_fn=h.diff_fn,
                         emit=h.events.append)
        self.assertEqual((r["change"], r["risk_flags"]), ({"files": 1, "top_dirs": 1, "door": "one-way"}, ["data_migration"]))

    def test_a_failed_run_still_ignores_files_dirty_before_it(self):
        dirty = {"is_repo": True, "diff": "d", "files": ["old.py"], "untracked": []}
        h = Harness(diff=dirty, changes_after=0)
        h.fail_on = 1
        r = h.run("L2")
        self.assertEqual((r["status"], r["change"]), ("error", None))

    def test_route_flags_keep_the_door_when_every_path_is_filtered(self):
        dirty = {"is_repo": True, "diff": "d", "files": ["old.py"], "untracked": []}
        r = Harness(diff=dirty, changes_after=0).run("L2", risk_flags=("data_migration",))
        self.assertEqual((r["change"], r["risk_flags"]), (None, ["data_migration"]))

    def test_review_only_counts_the_whole_diff_under_review(self):
        r = Harness(diff=REPO).run("L2", target="review_only")
        self.assertEqual(r["change"]["files"], 2)


GATE_CMD = {"overall": "passed", "checks": {"test": {"status": "passed", "command": "python3 -m unittest",
                                                    "source": "AGENTS.md"}}}
GATE_CMD_BAD = {"overall": "failed", "checks": {"test": {"status": "failed", "command": "python3 -m unittest",
                                                        "source": "AGENTS.md", "output_tail": "boom"}}}
GATE_CMD_INCOMPLETE = {"overall": "incomplete", "checks": {"test": {"status": "passed", "command": "python3 -m unittest",
                                                                   "source": "AGENTS.md"},
                                                          "lint": {"status": "not_run", "reason": "none"}}}
WITH_TESTS = {**REPO, "files": ["shop/pricing.py"], "untracked": ["tests/test_pricing.py"]}
DIRTY_BEFORE = {"is_repo": True, "diff": "d", "files": ["old.py"], "untracked": []}
PASSES = {"verdict": "passes_without_change", "reason": None, "tests": ["tests/test_pricing.py"], "duration_s": 0.1}
FAILS = {**PASSES, "verdict": "fails_without_change"}


def patch_probe(**kw):
    return mock.patch.object(pb, "probe_without_change", **kw)


class ProbeFlowTest(unittest.TestCase):
    """The test-without-change probe is reported, never decisive: status and exit_code stay what they were."""

    def test_passed_gate_with_changed_tests_probes_once_and_reports(self):
        h = Harness(gates=(GATE_CMD,), diff=WITH_TESTS)
        with patch_probe(return_value=PASSES) as probe:
            r = h.run("L2")
        probe.assert_called_once()
        cwd, paths, check, timeout_s = probe.call_args.args
        self.assertEqual((cwd, paths, timeout_s), ("/w", ["shop/pricing.py", "tests/test_pricing.py"], 300))
        self.assertEqual((check.kind, check.command, check.source, check.shell), ("test", "python3 -m unittest", "AGENTS.md", False))
        self.assertEqual((r["probe"], r["status"], r["exit_code"]), (PASSES, "ok", 0))
        self.assertEqual(h.kinds(), ["session_start", "gate", "probe", "done"])
        self.assertEqual(h.events[2], {"event": "probe", **PASSES})

    def test_a_config_test_command_keeps_its_shell_flag(self):
        gate = {"overall": "passed", "checks": {"test": {"status": "passed", "command": "make test && true", "source": "config"}}}
        with patch_probe(return_value=FAILS) as probe:
            Harness(gates=(gate,), diff=WITH_TESTS).run("L2")
        self.assertTrue(probe.call_args.args[2].shell)

    def test_probe_verdict_never_changes_status_or_exit_code(self):
        for verdict in (PASSES, FAILS, {**PASSES, "verdict": "inconclusive", "reason": "env"}):
            with patch_probe(return_value=verdict):
                r = Harness(gates=(GATE_CMD,), diff=WITH_TESTS).run("L2")
            self.assertEqual((r["status"], r["exit_code"]), ("ok", 0), verdict["verdict"])

    def test_probe_runs_after_the_gate_loop_and_before_the_review(self):
        h = Harness(gates=(GATE_CMD_BAD, GATE_CMD), diff=WITH_TESTS)
        with patch_probe(return_value=PASSES) as probe:
            h.run("L4")
        self.assertEqual(probe.call_count, 1)
        self.assertEqual(h.kinds(), ["session_start", "gate", "escalate", "gate", "probe", "session_start", "review", "done"])
        self.assertIn("PASS on the pre-change code", h.calls[-1]["argv"][-1])  # the reviewer gets the fact

    def test_review_fix_does_not_probe_again(self):
        h = Harness(gates=(GATE_CMD,), diff=WITH_TESTS, verdicts=[("changes_requested", 1)])
        with patch_probe(return_value=PASSES) as probe:
            r = h.run("L4")
        self.assertEqual((probe.call_count, r["status"], h.kinds().count("probe")), (1, "review_fixed", 1))

    def test_no_probe_when_the_gate_did_not_pass(self):
        for gate in (GATE_CMD_BAD, GATE_NR):
            h = Harness(gates=(gate,), diff=WITH_TESTS)
            with patch_probe(return_value=PASSES) as probe:
                r = h.run("L2")
            self.assertEqual(probe.call_count, 0, gate["overall"])
            self.assertEqual(r["probe"]["verdict"], "skipped")
            self.assertNotIn("probe", h.kinds())

    def test_an_incomplete_gate_with_a_passing_test_check_still_probes(self):
        # lint/typecheck/build not discovered make overall "incomplete"; the test check itself passed
        gate = {"overall": "incomplete", "checks": {**GATE_CMD_INCOMPLETE["checks"], "lint": {"status": "not_run"}}}
        h = Harness(gates=(gate,), diff=WITH_TESTS)
        with patch_probe(return_value=PASSES) as probe:
            r = h.run("L2")
        self.assertEqual((probe.call_count, r["probe"], r["status"]), (1, PASSES, "ok"))

    def test_a_failed_gate_or_a_not_run_test_check_is_skipped(self):
        failed = {"overall": "failed", "checks": {"test": {"status": "passed", "command": "x"}, "lint": {"status": "failed"}}}
        not_run = {"overall": "incomplete", "checks": {"test": {"status": "not_run"}, "lint": {"status": "passed"}}}
        for gate in (failed, not_run):
            with patch_probe(return_value=PASSES) as probe:
                r = Harness(gates=(gate,), diff=WITH_TESTS).run("L2")
            self.assertEqual((probe.call_count, r["probe"]["verdict"]), (0, "skipped"), gate["overall"])

    def test_no_probe_when_the_tree_was_dirty_before_the_run(self):
        h = Harness(gates=(GATE_CMD,), diff=WITH_TESTS)
        h.diff_fn = lambda cwd: WITH_TESTS if h.calls else DIRTY_BEFORE
        with patch_probe(return_value=PASSES) as probe:
            r = h.run("L2")
        self.assertEqual((probe.call_count, r["probe"]["verdict"]), (0, "skipped"))
        self.assertIn("not clean", r["probe"]["reason"])

    def test_no_probe_when_head_moved_during_the_run(self):
        h = Harness(gates=(GATE_CMD,), diff=WITH_TESTS)
        with mock.patch.object(rv, "git_head", side_effect=["aaa", "bbb"]), patch_probe(return_value=PASSES) as probe:
            r = h.run("L2")
        self.assertEqual((probe.call_count, r["probe"]["verdict"], r["probe"]["reason"]),
                         (0, "skipped", "HEAD moved during the run"))

    def test_probe_runs_when_head_is_unchanged(self):
        with mock.patch.object(rv, "git_head", return_value="aaa"), patch_probe(return_value=PASSES) as probe:
            Harness(gates=(GATE_CMD,), diff=WITH_TESTS).run("L2")
        self.assertEqual(probe.call_count, 1)

    def test_no_probe_outside_a_repository(self):
        h = Harness(gates=(GATE_CMD,), diff={"is_repo": False})
        with patch_probe(return_value=PASSES) as probe:
            r = h.run("L2")
        self.assertEqual((probe.call_count, r["probe"]["verdict"]), (0, "skipped"))

    def test_review_only_and_plan_only_have_no_probe(self):
        for target in ("review_only", "plan_only"):
            h = Harness(gates=(GATE_CMD,), diff=WITH_TESTS)
            with patch_probe(return_value=PASSES) as probe:
                r = h.run("L2", target=target)
            self.assertEqual((probe.call_count, r["probe"], "probe" in h.kinds()), (0, None, False), target)

    def test_no_changes_run_has_no_probe(self):
        r = Harness(changes_after=None).run("L2")
        self.assertIsNone(r["probe"])

    def test_without_test_files_the_real_probe_skips_silently(self):
        r = Harness(gates=(GATE_CMD,)).run("L2")  # REPO changes no test file; cwd /w does not exist: nothing may run
        self.assertEqual((r["probe"]["verdict"], r["probe"]["reason"]), ("skipped", "no test files changed"))

    def test_a_raising_probe_is_recorded_as_inconclusive_and_the_run_is_unchanged(self):
        h = Harness(gates=(GATE_CMD,), diff=WITH_TESTS)
        with patch_probe(side_effect=RuntimeError("kaboom")):
            r = h.run("L2")
        self.assertEqual((r["status"], r["exit_code"], r["probe"]["verdict"]), ("ok", 0, "inconclusive"))
        self.assertIn("kaboom", r["probe"]["reason"])
        self.assertEqual(h.kinds(), ["session_start", "gate", "probe", "done"])


class ReviewPromptProbeTest(unittest.TestCase):
    BASE = rv.review_prompt("req", REPO, GATE_OK)

    def test_unchanged_for_none_skipped_and_inconclusive(self):
        for probe in (None, {}, {"verdict": "skipped", "reason": "x"}, {"verdict": "inconclusive", "reason": "y"}):
            self.assertEqual(rv.review_prompt("req", REPO, GATE_OK, probe=probe), self.BASE)

    def test_passes_without_change_is_stated_as_a_fact(self):
        text = rv.review_prompt("req", REPO, GATE_OK, probe=PASSES)
        self.assertIn("Probe: the tests changed in this run PASS on the pre-change code, so they do not guard the change, "
                      "unless the request only adds tests for existing behaviour.", text)
        self.assertTrue(text.endswith("VERDICT: approved|changes_requested\nFINDINGS: <n>"))

    def test_fails_without_change_is_confirmed(self):
        text = rv.review_prompt("req", REPO, GATE_OK, probe=FAILS)
        self.assertIn("Probe: the changed tests failed on the pre-change code.", text)
        self.assertNotIn("PASS on the pre-change", text)
        self.assertNotIn("Last output", text)  # no tail, no extra block

    def test_fails_without_change_carries_a_truncated_output_tail(self):
        tail = "x" * 900 + "ImportError: no module named newmod"
        text = rv.review_prompt("req", REPO, GATE_OK, probe={**FAILS, "output_tail": tail})
        self.assertIn("Probe: the changed tests failed on the pre-change code.", text)
        self.assertIn("ImportError: no module named newmod", text)
        self.assertNotIn("x" * 600, text)  # at most 500 chars of it
        self.assertTrue(text.endswith("VERDICT: approved|changes_requested\nFINDINGS: <n>"))

    def test_other_verdicts_ignore_an_output_tail(self):
        for verdict in ("skipped", "inconclusive"):
            self.assertEqual(rv.review_prompt("req", REPO, GATE_OK, probe={"verdict": verdict, "output_tail": "boom"}), self.BASE)

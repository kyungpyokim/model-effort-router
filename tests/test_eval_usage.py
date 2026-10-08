import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from evaluation import usage

FIX = Path(__file__).resolve().parent / "fixtures"
ROLL = FIX / "rollouts"
ROOT = "01a0f40a-7449-7100-bb6b-978b137bb996"


def u(i=0, c=0, o=0, r=0):
    return {"input": i, "cached_input": c, "output": o, "reasoning_output": r}


class ParseTest(unittest.TestCase):
    def test_normalize_maps_codex_keys_and_defaults_missing_to_zero(self):
        self.assertEqual(usage.normalize({"input_tokens": 5, "output_tokens": 2}), u(5, 0, 2, 0))
        self.assertEqual(usage.normalize(None), u())

    def test_total_is_input_plus_output(self):
        self.assertEqual(usage.total_tokens(u(10, 9, 3, 2)), 13)  # cached is a subset of input, reasoning of output

    def test_exec_stream_takes_last_cumulative_usage_per_thread(self):
        text = (
            (FIX / "exec_router.jsonl").read_text()
            + json.dumps({"type": "turn.completed", "usage": {"input_tokens": 400000, "output_tokens": 1100}})
            + "\nnot json\n"
        )
        tid, total = usage.exec_stream_usage(text)
        self.assertEqual((tid, total), (ROOT, u(400000, 374784, 1100, 0)))

    def test_exec_stream_resume_is_cumulative_not_summed_and_threads_are_summed(self):
        def run(tid, i):
            return (
                json.dumps({"type": "thread.started", "thread_id": tid})
                + "\n"
                + json.dumps({"type": "turn.completed", "usage": {"input_tokens": i, "output_tokens": i // 10}})
                + "\n"
            )

        text = run("A", 100) + run("A", 250) + run("B", 40)  # A resumed: 250 is the session total
        self.assertEqual(usage.exec_stream_usage(text), ("A", u(290, 0, 29, 0)))
        self.assertEqual(usage.exec_stream_usage_by_thread(text), {"A": u(250, 0, 25, 0), "B": u(40, 0, 4, 0)})

    def test_exec_stream_without_usage_is_zero(self):
        self.assertEqual(usage.exec_stream_usage("")[1], u())

    def test_rollout_takes_last_cumulative_total_ignoring_null_info(self):
        r = usage.read_rollout(ROLL / "rollout-plan.jsonl")
        self.assertEqual(r["usage"], u(45000, 30000, 900, 300))
        self.assertEqual((r["thread_source"], r["agent_path"]), ("subagent", "/root/mer_plan"))
        self.assertEqual(r["session_id"], ROOT)

    def test_rollout_without_token_count_has_no_usage_not_zero(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "rollout-x.jsonl"
            p.write_text('{"type":"session_meta","payload":{"id":"a"}}\ngarbage\n')
            self.assertIsNone(usage.read_rollout(p)["usage"])

    def test_stage_of_agent_path(self):
        self.assertEqual(usage.stage_of("/root/mer_implement"), "implement")
        self.assertEqual(usage.stage_of("/root/review_isolated"), "other")
        self.assertEqual(usage.stage_of(None), "other")

    def test_find_rollouts_filters_by_root_session(self):
        with tempfile.TemporaryDirectory() as d:
            nested = Path(d) / "2026" / "10" / "01"
            nested.mkdir(parents=True)
            for f in ROLL.glob("*.jsonl"):
                shutil.copy(f, nested / f.name)
            found = sorted(p.name for p in usage.find_rollouts(d, ROOT))
            self.assertEqual(
                found, ["rollout-implement.jsonl", "rollout-main.jsonl", "rollout-plan.jsonl", "rollout-review.jsonl"]
            )
            self.assertEqual(usage.find_rollouts(Path(d) / "missing", ROOT), [])

    def test_find_rollouts_skips_files_older_than_run_start_without_parsing_them(self):
        with tempfile.TemporaryDirectory() as d:
            old, new = Path(d) / "rollout-old.jsonl", Path(d) / "rollout-new.jsonl"
            shutil.copy(ROLL / "rollout-plan.jsonl", old)
            shutil.copy(ROLL / "rollout-review.jsonl", new)
            os.utime(old, (1000, 1000))
            self.assertEqual(
                [p.name for p in usage.find_rollouts(d, ROOT, since_mtime=time.time() - 60)], ["rollout-new.jsonl"]
            )

    def test_find_rollouts_accepts_several_thread_ids(self):
        found = {p.name for p in usage.find_rollouts(ROLL, {ROOT, "nope"})}
        self.assertIn("rollout-main.jsonl", found)
        self.assertEqual(usage.find_rollouts(ROLL, set()), [])

    def test_forked_subagent_keeps_its_own_meta_not_the_copied_parent_one(self):
        """Codex forks a spawned subagent's rollout with the parent's session_meta copied after its own."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "rollout-fork.jsonl"
            p.write_text(
                '{"type":"session_meta","payload":{"id":"child","session_id":"%s","thread_source":"subagent",'
                '"agent_path":"/root/tdd_review"}}\n'
                % ROOT
                + '{"type":"session_meta","payload":{"id":"%s","session_id":"%s","thread_source":"user"}}\n'
                % (ROOT, ROOT)
            )
            r = usage.read_rollout(p)
            self.assertEqual((r["id"], r["thread_source"], r["agent_path"]), ("child", "subagent", "/root/tdd_review"))
            agg = usage.aggregate('{"type":"thread.started","thread_id":"%s"}' % ROOT, [p])
            self.assertEqual(agg["subagent_rollouts"], 1)  # never folded into (or dropped from) the main session

    def test_find_rollouts_reads_only_the_first_session_meta_line_to_filter(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "rollout-big.jsonl"
            p.write_text(
                '{"type":"session_meta","payload":{"session_id":"other"}}\n'
                + '{"type":"session_meta","payload":{"session_id":"%s"}}\n' % ROOT
            )
            self.assertEqual(usage.find_rollouts(d, ROOT), [])


class AggregateTest(unittest.TestCase):
    def rollouts(self):
        return sorted(ROLL.glob("rollout-*.jsonl"))

    def test_sums_orchestrator_classifier_and_each_stage(self):
        agg = usage.aggregate((FIX / "exec_router.jsonl").read_text(), self.rollouts(), classifier=u(29757, 6912, 20))
        self.assertEqual(agg["orchestrator"], u(384934, 374784, 1085))
        self.assertEqual(agg["classifier"], u(29757, 6912, 20))
        self.assertEqual(set(agg["stages"]), {"plan", "implement", "review"})
        self.assertEqual(agg["stages"]["implement"], u(60000, 10000, 3000, 500))
        # non-subagent rollouts (main, unrelated) are ignored when the exec stream gives the main session
        expected = (384934 + 1085) + (29757 + 20) + (45000 + 900) + (60000 + 3000) + (30000 + 700)
        self.assertEqual(agg["total"], expected)

    def test_repeated_stage_rollouts_are_summed(self):
        with tempfile.TemporaryDirectory() as d:
            paths = []
            for n in (1, 2):
                p = Path(d) / f"rollout-impl{n}.jsonl"
                shutil.copy(ROLL / "rollout-implement.jsonl", p)
                paths.append(p)
            agg = usage.aggregate(None, paths)
            self.assertEqual(agg["stages"]["implement"], u(120000, 20000, 6000, 1000))

    def test_main_rollout_used_when_no_exec_stream(self):
        agg = usage.aggregate(None, [ROLL / "rollout-main.jsonl", ROLL / "rollout-review.jsonl"])
        self.assertEqual(agg["orchestrator"], u(384934, 374784, 1085))
        self.assertEqual(list(agg["stages"]), ["review"])

    def test_exec_stream_wins_over_main_rollout_no_double_count(self):
        agg = usage.aggregate((FIX / "exec_router.jsonl").read_text(), [ROLL / "rollout-main.jsonl"])
        self.assertEqual(agg["total"], 384934 + 1085)

    def test_subagent_rollout_without_usage_is_reported_not_zeroed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "rollout-x.jsonl"
            p.write_text(
                '{"type":"session_meta","payload":{"id":"a","thread_source":"subagent",'
                '"agent_path":"/root/mer_review"}}\n'
            )
            agg = usage.aggregate(None, [p, ROLL / "rollout-plan.jsonl"])
            self.assertEqual(agg["stages_without_usage"], ["review"])
            self.assertEqual(agg["subagent_rollouts"], 2)
            self.assertNotIn("review", agg["stages"])

    def test_clean_run_reports_no_missing_usage(self):
        agg = usage.aggregate(None, self.rollouts())
        self.assertEqual((agg["stages_without_usage"], agg["subagent_rollouts"]), ([], 3))

    def test_extra_main_usage_added_for_threads_without_rollout(self):
        agg = usage.aggregate(None, [ROLL / "rollout-main.jsonl"], extra_main=u(10, 0, 5, 0))
        self.assertEqual(agg["orchestrator"], u(384944, 374784, 1090))

    def test_classifier_absent_stays_none_and_empty_run_is_zero(self):
        agg = usage.aggregate(None, [])
        self.assertIsNone(agg["classifier"])
        self.assertEqual((agg["total"], agg["stages"], agg["subagent_rollouts"]), (0, {}, 0))


if __name__ == "__main__":
    unittest.main()

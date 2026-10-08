import json
import os
import stat
import tempfile
import time
import unittest

from model_effort_router.context import summary
from model_effort_router.context.summary import Stored, anchor_at, build_context, pending
from model_effort_router.context.transcripts import Turn, read_turns

TURNS = (
    Turn("user", "u0 add retries"),
    Turn("assistant", "a1 plan: retries param"),
    Turn("user", "u2 응 만들어줘"),
    Turn("assistant", "a3 done"),
)


def ctx(turns, stored, max_chars=6000):
    base, fresh, _ = pending(turns, stored)
    return build_context(base, fresh, max_chars)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.sdir = os.path.join(self._tmp.name, "state")

    def test_roundtrip_is_private_and_leaves_no_temp_files(self):
        anchor = anchor_at(TURNS, 3)
        summary.save(self.sdir, "s1", "the summary", anchor)
        self.assertEqual(summary.load(self.sdir, "s1"), Stored("the summary", anchor))
        path = summary.summary_path(self.sdir, "s1")
        self.assertTrue(path.endswith(".summary.json"))
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(os.listdir(self.sdir), [os.path.basename(path)])

    def test_sessions_do_not_share_a_summary_and_logs_are_untouched(self):
        summary.save(self.sdir, "a/b", "one", anchor_at(TURNS, 1))
        summary.save(self.sdir, "a_b", "two", anchor_at(TURNS, 2))
        self.assertEqual(
            (summary.load(self.sdir, "a/b").summary, summary.load(self.sdir, "a_b").summary), ("one", "two")
        )
        self.assertFalse(any(n.endswith(".log.jsonl") for n in os.listdir(self.sdir)))

    def test_missing_or_corrupt_store_loads_empty(self):
        self.assertEqual(summary.load(self.sdir, "s1"), Stored())
        os.makedirs(self.sdir)
        for text in (
            "{not json",
            "[]",
            '{"summary": 5, "anchor": []}',
            '{"summary": "s", "anchor": "x"}',
            '{"summary": "s", "anchor": [1]}',
            '{"summary": "s", "anchor": ["a", "b", "c"]}',
        ):
            with open(summary.summary_path(self.sdir, "s1"), "w") as f:
                f.write(text)
            with self.subTest(text=text):
                self.assertEqual(summary.load(self.sdir, "s1"), Stored())

    def test_lock_is_exclusive_and_released(self):
        with summary.locked(self.sdir, "s1") as first:
            with summary.locked(self.sdir, "s1") as second:
                self.assertEqual((first, second), (True, False))
            with summary.locked(self.sdir, "other") as other:
                self.assertTrue(other)
        with summary.locked(self.sdir, "s1") as again:
            self.assertTrue(again)

    def test_prune_removes_old_summaries_and_locks_but_not_fresh_or_kept_ones(self):
        summary.save(self.sdir, "old", "x", ())
        summary.save(self.sdir, "new", "x", ())
        summary.save(self.sdir, "kept", "x", ())
        with summary.locked(self.sdir, "old"), summary.locked(self.sdir, "kept"):
            pass
        log = os.path.join(self.sdir, "old-00000000.log.jsonl")
        open(log, "w").close()
        stale = time.time() - 15 * 86400
        for sid in ("old", "kept"):
            for path in (summary.summary_path(self.sdir, sid), summary.lock_path(self.sdir, sid)):
                os.utime(path, (stale, stale))
        os.utime(log, (stale, stale))
        summary.prune(self.sdir, keep=(summary.summary_path(self.sdir, "kept"), summary.lock_path(self.sdir, "kept")))
        left = set(os.listdir(self.sdir))
        self.assertEqual(
            left,
            {
                os.path.basename(p)
                for p in (
                    summary.summary_path(self.sdir, "new"),
                    summary.summary_path(self.sdir, "kept"),
                    summary.lock_path(self.sdir, "kept"),
                )
            }
            | {os.path.basename(log)},
        )

    def test_prune_on_a_missing_dir_is_harmless(self):
        summary.prune(os.path.join(self.sdir, "nope"))


class BuildContextTest(unittest.TestCase):
    def test_nothing_known_gives_empty_context(self):
        self.assertEqual(build_context("", (), 6000), "")

    def test_summary_and_only_uncovered_turns(self):
        got = ctx(TURNS, Stored("goal: retries", anchor_at(TURNS, 2)))
        self.assertEqual(
            got, "Session summary:\ngoal: retries\n\nRecent turns:\nUser: u2 응 만들어줘\nAssistant: a3 done"
        )
        self.assertNotIn("u0", got)

    def test_without_summary_all_turns_are_recent(self):
        got = ctx(TURNS, Stored())
        self.assertTrue(got.startswith("Session summary:\n(none)\n\nRecent turns:\nUser: u0 add retries"))

    def test_summary_without_new_turns(self):
        self.assertEqual(
            ctx(TURNS, Stored("goal", anchor_at(TURNS, 4))), "Session summary:\ngoal\n\nRecent turns:\n(none)"
        )

    def test_budget_keeps_the_newest_turns_and_never_overflows(self):
        turns = tuple(Turn("user" if i % 2 == 0 else "assistant", f"t{i:02d} " + "x" * 300) for i in range(20))
        got = ctx(turns, Stored("s" * 5000), 1500)
        self.assertLessEqual(len(got), 1500)
        self.assertIn("t19", got)
        self.assertNotIn("t00", got)
        self.assertLess(got.index("t18"), got.index("t19"))  # chronological order

    def test_long_turns_keep_their_head_and_tail(self):
        got = ctx((Turn("assistant", "PLANHEAD " + "m" * 5000 + " PLANTAIL"),), Stored())
        self.assertIn("PLANHEAD", got)
        self.assertIn("PLANTAIL", got)
        self.assertLess(len(got), 3000)


class AnchorTest(unittest.TestCase):
    def test_pending_starts_after_the_anchor(self):
        self.assertEqual(pending(TURNS, Stored("s", anchor_at(TURNS, 2))), ("s", TURNS[2:], 2))
        self.assertEqual(pending(TURNS, Stored("s", anchor_at(TURNS, 4))), ("s", (), 4))
        self.assertEqual(pending(TURNS, Stored("s", anchor_at(TURNS, 1))), ("s", TURNS[1:], 1))

    def test_unfound_anchor_keeps_the_summary_and_treats_the_window_as_pending(self):
        stale = anchor_at((Turn("user", "gone"), Turn("assistant", "gone too")), 2)
        self.assertEqual(pending(TURNS, Stored("keep me", stale)), ("keep me", TURNS, 0))

    def test_a_repeated_message_does_not_move_the_anchor_forward(self):
        turns = (Turn("assistant", "plan A"), Turn("user", "진행"), Turn("assistant", "plan B"), Turn("user", "진행"))
        self.assertEqual(pending(turns, Stored("s", anchor_at(turns, 2)))[1], turns[2:])  # not just "the last 진행"

    def test_needs_refresh(self):
        self.assertFalse(summary.needs_refresh(TURNS, Stored("s", anchor_at(TURNS, 4))))
        self.assertFalse(summary.needs_refresh(TURNS, Stored()))  # below the minimum amount of new text
        big = (Turn("user", "x" * summary.REFRESH_MIN_CHARS),)
        self.assertTrue(summary.needs_refresh(big, Stored()))

    def test_anchor_survives_a_moving_tail_window(self):
        """Regression: past the read cap only the tail is parsed, so a turn count drifts; the anchor must not."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.jsonl")

            def write(texts):
                with open(path, "w") as f:
                    for role, text in texts:
                        f.write(json.dumps({"type": role, "message": {"content": text}}) + "\n")

            history = [("user" if i % 2 == 0 else "assistant", f"turn {i:03d} " + "x" * 40) for i in range(60)]
            write(history)
            window = read_turns(path, "claude", max_bytes=1500)
            self.assertTrue(10 < len(window) < 60)
            stored = Stored("SUMMARY OF EVERYTHING", anchor_at(window, len(window)))
            write(history + [("assistant", "PLAN: do X. approve?"), ("user", "진행")])
            moved = read_turns(path, "claude", max_bytes=1500)
            base, fresh, _ = pending(moved, stored)
            self.assertEqual(base, "SUMMARY OF EVERYTHING")
            self.assertEqual([t.text for t in fresh], ["PLAN: do X. approve?", "진행"])
            write(history[-3:] + [("assistant", "PLAN: do X. approve?")])  # the window shrinks below what was covered
            base, fresh, _ = pending(read_turns(path, "claude", max_bytes=1500), stored)
            self.assertEqual(base, "SUMMARY OF EVERYTHING")
            self.assertIn("PLAN: do X. approve?", [t.text for t in fresh])


if __name__ == "__main__":
    unittest.main()

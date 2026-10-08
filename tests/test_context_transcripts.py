import json
import os
import tempfile
import unittest
from pathlib import Path

from model_effort_router.context import transcripts
from model_effort_router.context.transcripts import Turn, read_turns

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "transcripts"


class ReadTurnsTest(unittest.TestCase):
    def test_claude_keeps_only_user_and_assistant_text(self):
        got = read_turns(str(FIXTURES / "claude-session.jsonl"), "claude")
        self.assertEqual(
            got,
            (
                Turn("user", "Add a retry option to the fetch helper."),
                Turn("assistant", "Plan: add a retries parameter, then update the two callers."),
                Turn(
                    "user", "Please also add a --timeout flag.\n\nThanks."
                ),  # a reminder-only user turn is dropped entirely
                Turn("user", "응 만들어줘"),
                Turn("assistant", "Earlier work: the fetch helper was refactored."),
                Turn("assistant", "Done. Added retries."),
            ),
        )

    def test_codex_keeps_only_real_user_and_assistant_messages(self):
        got = read_turns(str(FIXTURES / "codex-rollout.jsonl"), "codex")
        self.assertEqual(
            got,
            (
                Turn("user", "Fix the flaky parser test."),
                Turn("assistant", "Proposal: seed the RNG, then rerun the suite."),
                Turn("user", "진행"),
            ),
        )

    def test_tool_output_never_appears(self):
        for name, host in (("claude-session.jsonl", "claude"), ("codex-rollout.jsonl", "codex")):
            got = repr(read_turns(str(FIXTURES / name), host))
            for secret in ("SECRET_TOOL_OUTPUT", "SYSTEM_REMINDER_BODY", "HOOK_CONTEXT_BODY"):
                self.assertNotIn(secret, got)

    def test_unusable_inputs_give_no_turns(self):
        with tempfile.TemporaryDirectory() as tmp:
            link = os.path.join(tmp, "link.jsonl")
            os.symlink(FIXTURES / "claude-session.jsonl", link)
            fifo = os.path.join(tmp, "fifo")
            os.mkfifo(fifo)
            for path in (None, "", 7, "relative.jsonl", os.path.join(tmp, "missing"), tmp, link, fifo):
                with self.subTest(path=path):
                    self.assertEqual(read_turns(path, "claude"), ())
        self.assertEqual(read_turns(str(FIXTURES / "claude-session.jsonl"), "opencode"), ())

    def test_long_turn_is_clipped_to_head_and_tail(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"type": "user", "message": {"content": "H" * 100 + "x" * 20000 + "T" * 100}}) + "\n")
        self.addCleanup(os.unlink, f.name)
        (turn,) = read_turns(f.name, "claude")
        self.assertLessEqual(len(turn.text), transcripts.MAX_TURN_CHARS + 5)
        self.assertTrue(turn.text.startswith("H" * 100) and turn.text.endswith("T" * 100))

    def test_huge_file_is_read_from_the_tail_only(self):
        rows = [json.dumps({"type": "user", "message": {"content": f"turn-{i:03d}"}}) for i in range(200)]
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write("\n".join(rows) + "\n")
        self.addCleanup(os.unlink, f.name)
        got = read_turns(f.name, "claude", max_bytes=1000)
        self.assertTrue(0 < len(got) < 200)
        self.assertEqual(got[-1], Turn("user", "turn-199"))
        self.assertTrue(all(t.text.startswith("turn-") and len(t.text) == 8 for t in got))  # no half line


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from model_effort_router.host import advice, hosts, main_model as main_model_module
from model_effort_router.host.main_model import (
    MainReader,
    main_effort,
    main_model,
    normalize,
    save_session_model,
)
from model_effort_router.difficulty.decision import DifficultyDecision
from model_effort_router.policy.router import RoutePlan
from model_effort_router.policy.targeting import ROUTE


def plan(model="claude-opus-5-5", effort="high", options=None, role="fix"):
    return RoutePlan(
        ROUTE,
        "auto",
        DifficultyDecision(role, "low", "x"),
        (),
        model,
        "reasoning",
        "high",
        effort,
        model_options=options or (model,),
    )


def row(kind, **fields):
    return json.dumps({"type": kind, **fields})


def assistant(model, sidechain=False, ts=None):
    extra = {"timestamp": ts} if ts else {}
    return row("assistant", isSidechain=sidechain, message={"model": model, "content": []}, **extra)


def assistant_effort(effort, sidechain=False):
    return row("assistant", isSidechain=sidechain, effort=effort, message={"model": "m", "content": []})


def attachment(model_id):
    return row("attachment", isSidechain=False, attachment={"type": "model", "identity": {"modelId": model_id}})


class MainModelTest(unittest.TestCase):
    def transcript(self, *lines):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "t.jsonl"
        path.write_text("\n".join(lines) + "\n")
        return str(path)

    def test_normalize_ignores_case_space_and_context_suffix(self):
        self.assertEqual(normalize(" Claude-Sonnet-5-5[1m] "), "claude-sonnet-5-5")
        self.assertEqual(normalize("claude-haiku-4-5-20251001"), "claude-haiku-4-5")
        self.assertIsNone(normalize(""))
        self.assertIsNone(normalize(None))

    def test_claude_reads_last_main_assistant_model(self):
        path = self.transcript(
            assistant("claude-opus-5-5"), assistant("claude-haiku-4-5", sidechain=True), assistant("<synthetic>")
        )
        self.assertEqual(main_model({"transcript_path": path}, "claude"), "claude-opus-5-5")

    def test_claude_first_turn_falls_back_to_model_attachment(self):
        path = self.transcript(row("user", message={}), attachment("claude-sonnet-5-5[1m]"))
        self.assertEqual(main_model({"transcript_path": path}, "claude"), "claude-sonnet-5-5")

    def test_claude_later_attachment_wins_over_older_assistant(self):
        path = self.transcript(assistant("claude-opus-5-5"), attachment("claude-sonnet-5-5"))
        self.assertEqual(main_model({"transcript_path": path}, "claude"), "claude-sonnet-5-5")

    def test_claude_unknown_when_a_model_switch_is_not_yet_reflected(self):
        stdout = "<local-command-stdout>Set model to `Haiku 4.5` for this session only</local-command-stdout>"
        switches = {  # the two row shapes seen on real transcripts: interactive sessions, and `claude -p`
            "interactive": row("user", message={"role": "user", "content": stdout}),
            "print mode": row("system", subtype="local_command", content=stdout),
        }
        for shape, switch in switches.items():
            with self.subTest(shape):
                stale = self.transcript(assistant("claude-opus-5-5"), switch)
                self.assertIsNone(main_model({"transcript_path": stale}, "claude"))
                fresh = self.transcript(assistant("claude-opus-5-5"), switch, attachment("claude-sonnet-5-5[1m]"))
                self.assertEqual(main_model({"transcript_path": fresh}, "claude"), "claude-sonnet-5-5")

    def test_claude_rows_that_only_quote_the_switch_text_are_not_a_switch(self):
        text = "<local-command-stdout>Set model to `x`</local-command-stdout>"
        quoted = [
            row("assistant", isSidechain=False, message={"model": "claude-opus-5-5", "content": [{"text": text}]}),
            row("user", message={"content": [{"type": "tool_result", "content": text}]}),
            row("user", message={"content": f"see {text}"}),
        ]
        path = self.transcript(assistant("claude-opus-5-5"), *quoted)
        self.assertEqual(main_model({"transcript_path": path}, "claude"), "claude-opus-5-5")

    def test_session_start_model_is_the_fallback_only_without_transcript_evidence(self):
        sdir = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, sdir, True)
        save_session_model(sdir, "s1", "Claude-Sonnet-5-5")
        data = {"session_id": "s1", "transcript_path": "/nope"}
        self.assertEqual(main_model(data, "claude", sdir), "claude-sonnet-5-5")
        self.assertIsNone(main_model(data, "claude"))  # no state dir: nothing to read
        self.assertIsNone(main_model({**data, "session_id": "other"}, "claude", sdir))
        newer = self.transcript(assistant("claude-opus-5-5"))
        self.assertEqual(main_model({**data, "transcript_path": newer}, "claude", sdir), "claude-opus-5-5")
        switch = row("user", message={"content": "<local-command-stdout>Set model to `x`</local-command-stdout>"})
        pending = self.transcript(switch)
        self.assertIsNone(main_model({**data, "transcript_path": pending}, "claude", sdir))

    def test_session_start_without_a_valid_model_clears_the_stored_one(self):
        sdir = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, sdir, True)
        data = {"session_id": "s1", "transcript_path": "/nope"}
        save_session_model(sdir, "s1", "claude-sonnet-5-5")
        for raw in (None, "", 5, "<synthetic>"):
            save_session_model(sdir, "s1", "claude-sonnet-5-5")
            save_session_model(sdir, "s1", raw)
            self.assertIsNone(main_model(data, "claude", sdir), raw)

    def test_a_switch_value_beats_transcript_evidence_that_is_not_newer(self):
        sdir = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, sdir, True)
        data = {"session_id": "s1", "transcript_path": "/nope"}
        save_session_model(sdir, "s1", "claude-haiku-4-5-20251001", "switch")
        self.assertEqual(main_model(data, "claude", sdir), "claude-haiku-4-5")  # row not on disk yet
        stale = self.transcript(assistant("claude-opus-5-5"))
        self.assertEqual(main_model({**data, "transcript_path": stale}, "claude", sdir), "claude-haiku-4-5")
        switch = row("user", message={"content": "<local-command-stdout>Set model to `x`</local-command-stdout>"})
        both = self.transcript(assistant("claude-opus-5-5"), switch)
        self.assertEqual(main_model({**data, "transcript_path": both}, "claude", sdir), "claude-haiku-4-5")

    def stored_at(self, sdir, epoch, model="claude-haiku-4-5", source="switch"):
        with patch("model_effort_router.host.main_model.time.time", return_value=epoch):
            save_session_model(sdir, "s1", model, source)

    def test_a_reply_after_the_switch_lets_the_transcript_win(self):
        sdir = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, sdir, True)
        self.stored_at(sdir, 1_000_000)  # 1970-01-12T13:46:40Z
        data = {"session_id": "s1"}
        after = self.transcript(assistant("claude-opus-5-5", ts="1970-01-12T13:46:41.000Z"))
        self.assertEqual(main_model({**data, "transcript_path": after}, "claude", sdir), "claude-opus-5-5")
        before = self.transcript(assistant("claude-opus-5-5", ts="1970-01-12T13:46:39.000Z"))
        self.assertEqual(main_model({**data, "transcript_path": before}, "claude", sdir), "claude-haiku-4-5")
        for bad in ("garbage", "", None):
            path = self.transcript(assistant("claude-opus-5-5", ts=bad))
            self.assertEqual(main_model({**data, "transcript_path": path}, "claude", sdir), "claude-haiku-4-5")
        late = row(
            "user",
            message={"content": "<local-command-stdout>Set model to `x`</local-command-stdout>"},
            timestamp="1970-01-12T13:50:00.000Z",
        )
        path = self.transcript(assistant("claude-opus-5-5", ts="1970-01-12T13:46:39.000Z"), late)
        self.assertEqual(main_model({**data, "transcript_path": path}, "claude", sdir), "claude-haiku-4-5")
        # a reply after the switch also beats a later-written (delayed) switch row
        path = self.transcript(assistant("claude-opus-5-5", ts="1970-01-12T13:46:41.000Z"), late)
        self.assertIsNone(main_model({**data, "transcript_path": path}, "claude", sdir))

    def test_a_start_value_ignores_timestamps(self):
        sdir = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, sdir, True)
        self.stored_at(sdir, 1_000_000, source="start")
        path = self.transcript(assistant("claude-opus-5-5", ts="1970-01-12T13:46:39.000Z"))
        self.assertEqual(main_model({"session_id": "s1", "transcript_path": path}, "claude", sdir), "claude-opus-5-5")

    def test_unknown_source_invalidates_the_stored_value(self):
        sdir = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, sdir, True)
        data = {"session_id": "s1", "transcript_path": "/nope"}
        for source in ("resume", "", None, 5):
            self.stored_at(sdir, 1_000_000, source=source)
            self.assertIsNone(main_model(data, "claude", sdir), source)

    def test_an_invalid_switch_target_removes_the_stored_value(self):
        sdir = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, sdir, True)
        save_session_model(sdir, "s1", "claude-opus-5-5", "switch")
        save_session_model(sdir, "s1", None, "switch")
        self.assertIsNone(main_model({"session_id": "s1", "transcript_path": "/nope"}, "claude", sdir))

    def test_claude_unknown_when_missing_garbage_or_empty(self):
        self.assertIsNone(main_model({"transcript_path": "/nope"}, "claude"))
        self.assertIsNone(main_model({}, "claude"))
        self.assertIsNone(main_model({"transcript_path": self.transcript("{not json", "[]")}, "claude"))

    def test_codex_uses_payload_model_and_other_hosts_are_unknown(self):
        self.assertEqual(main_model({"model": "GPT-6.1-Sol"}, "codex"), "gpt-6.1-sol")
        self.assertIsNone(main_model({}, "codex"))
        self.assertIsNone(main_model({"model": "x", "transcript_path": "/x"}, "antigravity"))

    def test_claude_reads_last_main_assistant_effort(self):
        path = self.transcript(
            assistant_effort("low"), assistant_effort("max", sidechain=True), assistant_effort("high")
        )
        self.assertEqual(main_effort({"transcript_path": path}, "claude"), "high")

    def test_unknown_without_evidence_or_on_codex(self):
        path = self.transcript(assistant("claude-opus-5-5"), assistant_effort(7), assistant_effort(""))
        self.assertIsNone(main_effort({"transcript_path": path}, "claude"))
        self.assertIsNone(main_effort({"transcript_path": path}, "codex"))
        self.assertIsNone(main_effort({"transcript_path": "relative.jsonl"}, "claude"))

    def test_antigravity_reads_settings_change_model_and_effort(self):
        content = (
            "<USER_REQUEST>\nFix bug\n</USER_REQUEST>\n"
            "<USER_SETTINGS_CHANGE>\n"
            "The user changed setting `Model Selection` from None to Gemini 3.8 Flash (High). "
            "No need to comment on this change if the user doesn't ask about it.\n"
            "</USER_SETTINGS_CHANGE>"
        )
        path = self.transcript(row("USER_INPUT", content=content, source="USER_EXPLICIT"))
        self.assertEqual(main_model({"transcript_path": path}, "antigravity"), "gemini-3.8-flash")
        self.assertEqual(main_effort({"transcript_path": path}, "antigravity"), "high")

    def test_antigravity_unknown_when_no_settings_change(self):
        path = self.transcript(
            row("USER_INPUT", content="<USER_REQUEST>Fix bug</USER_REQUEST>", source="USER_EXPLICIT")
        )
        self.assertIsNone(main_model({"transcript_path": path}, "antigravity"))
        self.assertIsNone(main_effort({"transcript_path": path}, "antigravity"))

    def test_antigravity_ignores_settings_quoted_in_other_content(self):
        setting = "The user changed setting `Model Selection` from None to Gemini 3.8 Flash (High)."
        block = f"<USER_SETTINGS_CHANGE>\n{setting}\n</USER_SETTINGS_CHANGE>"
        for kind, source, content in (
            ("ASSISTANT_OUTPUT", "MODEL", block),
            ("USER_INPUT", "TOOL", block),
            ("USER_INPUT", "USER_EXPLICIT", setting),
            ("USER_INPUT", "USER_EXPLICIT", f"<USER_REQUEST>{block}</USER_REQUEST>"),
        ):
            with self.subTest(kind=kind, source=source, content=content):
                path = self.transcript(row(kind, source=source, content=content))
                self.assertIsNone(main_model({"transcriptPath": path}, "antigravity"))
                self.assertIsNone(main_effort({"transcriptPath": path}, "antigravity"))

    def test_a_registered_reader_serves_a_new_host_without_touching_the_dispatch(self):
        readers = {**main_model_module.READERS, "newhost": MainReader(lambda d, s: "m", lambda d, s: "e")}
        with patch.object(main_model_module, "READERS", readers):
            self.assertEqual(main_model({}, "newhost"), "m")
            self.assertEqual(main_effort({}, "newhost"), "e")


class AdviceRecommendationTest(unittest.TestCase):
    def test_advice_recommends_only_model_and_effort(self):
        for host, model in ((hosts.CLAUDE, "claude-opus-5-5"), (hosts.CODEX, "gpt-6.1-sol")):
            with self.subTest(host=host.name):
                note = advice.render(plan(model, "high", options=(model, "other-model")), host)
                self.assertIn(f"Recommended model: {model}; effort: high", note)
                self.assertIn("Other configured options: other-model", note)
                self.assertNotIn("Subagent", note)
                self.assertNotIn("Context Packet", note)
                self.assertNotIn("invoke:", note)
                self.assertEqual(advice.summary(plan(model), host)["action"], "recommend")

    def test_same_model_recommends_effort_without_delegation(self):
        note = advice.render(plan("claude-opus-5-5", "xhigh"), hosts.CLAUDE, main_model="claude-opus-5-5")
        self.assertIn("Main already uses claude-opus-5-5", note)
        self.assertIn("Recommended effort: xhigh", note)
        self.assertNotIn("Subagent", note)

    def test_matches_helper_is_tristate(self):
        self.assertIsNone(advice.matches(plan(), None))
        self.assertTrue(advice.matches(plan(), "Claude-Opus-5-5"))
        self.assertFalse(advice.matches(plan(), "claude-sonnet-5-5"))
        self.assertFalse(advice.matches(plan(), "opus"))


if __name__ == "__main__":
    unittest.main()

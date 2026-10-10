import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from model_effort_router.host import advice, hosts
from model_effort_router.host.main_model import main_model, normalize, save_session_model
from model_effort_router.difficulty.decision import DifficultyDecision
from model_effort_router.policy.router import RoutePlan
from model_effort_router.policy.targeting import ROUTE


def plan(model="claude-opus-5-5", effort="high", options=None):
    return RoutePlan(
        ROUTE,
        "auto",
        DifficultyDecision("fix", "low", "x"),
        (),
        model,
        None,
        "reasoning",
        "high",
        effort,
        model_options=options or (model,),
    )


CLAUDE_MODEL = "claude-opus-5-5"
GOLDEN_CLAUDE = "[model-effort-router] fix → reasoning · claude-opus-5-5 · effort high. Main: route this single task to a native Subagent using the host's supported model/effort controls, or handle it directly when Main's model/effort already match or project instructions require it. invoke: Agent(subagent_type=\"model-effort-router:effort-high\", model=\"opus\") (`opus` runs Claude Code's current opus model, which may differ from claude-opus-5-5). Build a compact Context Packet with task, context, decisions, constraints, relevant_files, expected_result. Use facts from the current request and relevant conversation to populate the packet, label unknowns, and include the completed packet directly in the host-native Subagent invocation. Do not forward the full conversation or private reasoning. Integrate the result, then decide whether another worker is needed. The hook provides advice only; it does not inspect Main's conversation or invoke the Subagent, and does not change this Main turn's model/settings. Other configured options: other-model (user-selectable, not automatic fallbacks)."
GOLDEN_CODEX = "[model-effort-router] fix → reasoning · gpt-6.1-sol · effort high. Main: route this single task to a native Subagent using the host's supported model/effort controls, or handle it directly when Main's model/effort already match or project instructions require it. Build a compact Context Packet with task, context, decisions, constraints, relevant_files, expected_result. Use facts from the current request and relevant conversation to populate the packet, label unknowns, and include the completed packet directly in the host-native Subagent invocation. Do not forward the full conversation or private reasoning. Integrate the result, then decide whether another worker is needed. The hook provides advice only; it does not inspect Main's conversation or invoke the Subagent, and does not change this Main turn's model/settings. Other configured options: other-model (user-selectable, not automatic fallbacks)."


def row(kind, **fields):
    return json.dumps({"type": kind, **fields})


def assistant(model, sidechain=False, ts=None):
    extra = {"timestamp": ts} if ts else {}
    return row("assistant", isSidechain=sidechain, message={"model": model, "content": []}, **extra)


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


class AdviceMatchTest(unittest.TestCase):
    def test_mismatch_is_unconditional_and_names_both_models(self):
        note = advice.render(plan(), "mer", hosts.CLAUDE, main_model="claude-sonnet-5-5")
        self.assertIn("Main model claude-sonnet-5-5 ≠ routed claude-opus-5-5: spawn the Subagent", note)
        self.assertIn('invoke: Agent(subagent_type="model-effort-router:effort-high", model="opus")', note)
        self.assertIn("skipped routing: <reason>", note)
        self.assertNotIn("project instructions require", note)
        self.assertNotIn("already match", note)
        self.assertTrue(note.rstrip().endswith("settings."))

    def test_codex_mismatch_gives_spawn_agent_invocation(self):
        note = advice.render(plan("gpt-6.1-sol", "medium"), "mer", hosts.CODEX, main_model="gpt-6-luna")
        self.assertIn(
            'invoke: spawn_agent(model="gpt-6.1-sol", reasoning_effort="medium", fork_turns="none", '
            "message=<Context Packet>)",
            note,
        )
        self.assertIn("asks for the model/reasoning_effort", note)
        self.assertIn(
            "Start your reply with one line naming the model that did the work: "
            "`[routed: gpt-6.1-sol · effort medium]` if the Subagent ran, or `[main: gpt-6-luna]`",
            note,
        )

    def test_codex_same_model_tags_reply_with_main_and_claude_gets_no_tag(self):
        note = advice.render(plan("gpt-6.1-sol", "medium"), "mer", hosts.CODEX, main_model="gpt-6.1-sol")
        self.assertIn("Start your reply with the line `[main: gpt-6.1-sol]`", note)
        for main in ("claude-sonnet-5-5", "claude-opus-5-5"):
            self.assertNotIn("Start your reply", advice.render(plan(), "mer", hosts.CLAUDE, main_model=main))

    def test_match_says_proceed_in_main_with_routed_effort(self):
        note = advice.render(plan(effort="xhigh"), "mer", hosts.CLAUDE, main_model="claude-opus-5-5")
        self.assertIn("Main already runs claude-opus-5-5; no Subagent needed. Proceed directly in Main", note)
        self.assertIn("Main cannot change its own effort; routed effort is xhigh", note)
        self.assertNotIn("Context Packet", note)

    def test_unknown_main_model_keeps_legacy_text(self):
        legacy = advice.render(plan(), "mer", hosts.CLAUDE)
        self.assertIn("handle it directly when Main's model/effort already match", legacy)
        self.assertEqual(legacy, advice.render(plan(), "mer", hosts.CLAUDE, main_model=None))

    def test_unknown_path_is_byte_identical_to_the_legacy_advice(self):
        for model, host, golden in (
            (CLAUDE_MODEL, hosts.CLAUDE, GOLDEN_CLAUDE),
            ("gpt-6.1-sol", hosts.CODEX, GOLDEN_CODEX),
        ):
            p = plan(model, "high", options=(model, "other-model"))
            self.assertEqual(advice.render(p, "mer", host), golden)

    def test_claude_model_without_agent_alias_falls_back_to_legacy_advice(self):
        p = plan("provider/model-id")
        note = advice.render(p, "mer", hosts.CLAUDE, main_model="claude-sonnet-5-5")
        self.assertEqual(note, advice.render(p, "mer", hosts.CLAUDE))
        self.assertNotIn("spawn the Subagent", note)

    def test_matches_helper_is_tristate(self):
        self.assertIsNone(advice.matches(plan(), None))
        self.assertTrue(advice.matches(plan(), "Claude-Opus-5-5"))
        self.assertFalse(advice.matches(plan(), "claude-sonnet-5-5"))
        self.assertFalse(advice.matches(plan(), "opus"))  # no alias fuzzy matching


if __name__ == "__main__":
    unittest.main()

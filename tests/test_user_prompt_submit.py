import json
import unittest
from unittest.mock import patch

from model_effort_router.difficulty.subscription import GUARD_ENV
from model_effort_router.context import summary
from model_effort_router.context.transcripts import read_turns
from model_effort_router.host import codex_hooks
from model_effort_router.policy.router import RoutePlan
from tests.fake_registry import FakeBackend
from tests.hook_helpers import DEV, PLUGIN, SID, HookCase, run_script


class UserPromptSubmitTest(HookCase):
    def context(self, proc):
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        hook = payload["hookSpecificOutput"]
        self.assertEqual(hook["hookEventName"], "UserPromptSubmit")
        return hook["additionalContext"]

    def test_advisory_includes_role_effort_model_and_context_packet(self):
        self.fake = {"role": "review", "effort": "medium", "confidence": 0.8}
        advice = self.context(self.submit("Review the diff in parser.py"))
        self.assertIn("review → reasoning · gpt-6.1-sol · effort medium", advice)
        self.assertIn("goal, decisions, constraints, actual diff, verification status/results", advice)
        self.assertIn("current request and relevant conversation", advice)
        self.assertIn("populate", advice)
        self.assertIn("native Subagent invocation", advice)
        self.assertIn("actual diff", advice)
        self.assertIn("verification status/results", advice)
        self.assertIn("not run", advice)
        self.assertIn("full conversation", advice)
        self.assertIn("private reasoning", advice)
        self.assertIn("does not change this Main turn", advice)
        self.assertNotIn("L1", advice)

    def test_active_project_name_is_passed_to_the_router_from_hook_cwd(self):
        data = {
            "session_id": SID,
            "cwd": str(self.repo),
            "transcript_path": "/missing",
            "prompt": "현재 진행 상황 파악",
        }
        with patch("model_effort_router.host.codex_hooks.route", return_value=RoutePlan("no_route", "auto")) as routed:
            codex_hooks.user_prompt_submit(data, self.env(), self.plugin)
        self.assertEqual(routed.call_args.kwargs["repo_summary"], self.repo.name)

    def test_empty_hook_cwd_falls_back_to_process_cwd(self):
        data = {"session_id": SID, "cwd": "", "transcript_path": "/missing", "prompt": "현재 진행 상황 파악"}
        with (
            patch("model_effort_router.host.codex_hooks.os.getcwd", return_value="/tmp/active-project"),
            patch("model_effort_router.host.codex_hooks.route", return_value=RoutePlan("no_route", "auto")) as routed,
        ):
            codex_hooks.user_prompt_submit(data, self.env(), self.plugin)
        self.assertEqual(routed.call_args.kwargs["repo_summary"], "active-project")

    def test_risk_floor_only_raises_effort_for_protected_roles(self):
        self.fake = {"role": "review", "effort": "low"}
        advice = self.context(self.submit("Review the migration that drops the old records in db.py"))
        self.assertIn("· effort high", advice)
        self.assertIn("review →", advice)

    def test_explicit_phase_override_skips_classifier(self):
        self.fake = {"raise": True}
        advice = self.context(self.submit("/router role=analysis effort=xhigh\nAnalyze parser.py"))
        self.assertIn("analysis →", advice)
        self.assertIn("· effort xhigh", advice)

    def test_classifier_failure_is_fail_open_and_recorded_without_prompt(self):
        self.fake = {"raise": True}
        proc = self.submit()
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))
        (event,) = self.log_events()
        self.assertEqual(
            (event["event"], event["target"], event["error_type"]), ("route", "error", "ClassificationError")
        )
        self.assertEqual(len(event["prompt_sha"]), 12)
        self.assertNotIn("ZEBRA_PROMPT_MARKER", json.dumps(event))
        self.assertNotIn("fake backend failure", json.dumps(event))

    def test_unsupported_effort_error_is_logged_not_silently_dropped(self):
        self.fake = {"effort": "max"}
        self.write_repo_config(
            {
                "difficulty": {"backend": "fake"},
                "models": {"codex": {"execution": {"primary": "gpt-6-luna", "efforts": ["low", "medium"]}}},
            }
        )
        proc = self.submit()
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))
        (event,) = self.log_events()
        self.assertEqual((event["target"], event["error_type"]), ("error", "ValueError"))

    def test_bad_config_and_garbage_input_fail_open(self):
        (self.repo / ".model-effort-router.json").write_text("{not json")
        self.assertEqual((self.submit().returncode, self.submit().stdout), (0, ""))
        proc = run_script("hooks/user_prompt_submit.py", stdin="not json", env=self.env())
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))

    def test_non_development_and_host_generated_prompts_are_not_classified(self):
        for prompt in (
            "Another Claude session sent a message:\n<agent-message>Fix the bug in parser.py</agent-message>",
            "<task-notification>refactor parser.py</task-notification>",
        ):
            proc = self.submit(prompt)
            self.assertEqual((proc.returncode, proc.stdout), (0, ""), prompt)
        self.assertEqual(self.log_events(), [])

    def test_regex_gated_prompt_is_silent_but_logged_without_prompt_text(self):
        proc = self.submit("What is the capital of France? ZEBRA_PROMPT_MARKER")
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))
        (event,) = self.log_events()
        self.assertEqual((event["event"], event["target"]), ("route", "no_route"))
        self.assertNotIn("decision", event)
        self.assertNotIn("ZEBRA_PROMPT_MARKER", json.dumps(event))

    def test_backend_target_routes_korean_follow_up_the_regex_would_drop(self):
        self.fake = {"role": "analysis", "effort": "low", "target": "route"}
        advice = self.context(self.submit("원인 파악해"))
        self.assertIn("analysis →", advice)
        self.assertEqual(self.log_events()[0]["target"], "route")

    def test_backend_no_route_is_silent_and_logged_with_decision(self):
        self.fake = {
            "role": "analysis",
            "effort": "low",
            "target": "no_route",
            "usage": {"input_tokens": 3, "output_tokens": 1},
        }
        proc = self.submit("Fix the bug in parser.py")
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))
        (event,) = self.log_events()
        self.assertEqual(
            (event["target"], event["decision"]["backend"], event["classifier_usage"]["input_tokens"]),
            ("no_route", "fake", 3),
        )

    def test_off_mode_writes_no_route_event(self):
        self.write_repo_config({"router": {"mode": "off"}, "difficulty": {"backend": "fake"}})
        self.assertEqual(self.submit().stdout, "")
        self.assertEqual(self.log_events(), [])

    def test_readonly_code_analysis_is_route_eligible(self):
        self.fake = {"role": "analysis", "effort": "high"}
        advice = self.context(self.submit("Analyze the authentication flow in auth.py"))
        self.assertIn("analysis →", advice)

    def test_off_and_manual_modes_remain_silent_without_phase_override(self):
        self.write_repo_config({"router": {"mode": "off"}, "difficulty": {"backend": "fake"}})
        self.assertEqual(self.submit().stdout, "")
        self.write_repo_config({"router": {"mode": "manual"}, "difficulty": {"backend": "fake"}})
        self.assertEqual(self.submit().stdout, "")

    def test_route_log_contains_hash_and_role_effort_without_prompt(self):
        self.fake = {"role": "fix", "effort": "medium"}
        self.context(self.submit())
        (event,) = self.log_events()
        self.assertEqual(
            (event["event"], event["decision"]["role"], event["decision"]["effort"]), ("route", "fix", "medium")
        )
        self.assertEqual((event["prompt_len"], len(event["prompt_sha"])), (len(DEV), 12))
        self.assertNotIn("ZEBRA_PROMPT_MARKER", json.dumps(event))
        self.assertNotIn("prompt", event)

    def test_log_failure_does_not_change_advisory_output(self):
        blocker = self.root / "file"
        blocker.write_text("x")
        proc = run_script(
            "hooks/user_prompt_submit.py",
            env=self.env(MER_STATE_DIR=str(blocker / "sub")),
            stdin=json.dumps({"session_id": "s", "cwd": str(self.repo), "prompt": DEV}),
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("[model-effort-router] implementation →", self.context(proc))


class SessionContextTest(HookCase):
    """In-process, with an injected spawner: no refresh process and no model CLI ever starts."""

    BIG = "B" * summary.REFRESH_MIN_CHARS

    def setUp(self):
        super().setUp()
        FakeBackend.inputs.clear()
        self.fake = {"target": "route", "role": "fix", "effort": "low"}  # a target-deciding backend, as Jev is
        self.spawned = []
        self.transcript = self.root / "t.jsonl"

    def write_transcript(self, *turns):
        rows = [{"type": role, "message": {"content": text}} for role, text in turns]
        self.transcript.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    def call(self, prompt="진행", host="claude", path=None, env_extra=None, spawn=None, version="0.160.1"):
        data = {
            "session_id": SID,
            "cwd": str(self.repo),
            "prompt": prompt,
            "transcript_path": str(path or self.transcript),
        }
        env = self.env(MER_HOST=host, **(env_extra or {}))
        return codex_hooks.user_prompt_submit(
            data, env, PLUGIN, spawn=spawn or (lambda *a: self.spawned.append(a)), version_probe=lambda: version
        )

    def test_summary_and_uncovered_turns_reach_the_classifier_without_the_current_prompt(self):
        self.write_transcript(("user", "add retries"), ("assistant", "plan: retries param"), ("user", "진행"))
        summary.save(
            str(self.state), SID, "goal: retries", summary.anchor_at(read_turns(str(self.transcript), "claude"), 1)
        )
        self.call("진행")
        (seen,) = FakeBackend.inputs
        self.assertEqual(seen.task, "진행")
        self.assertEqual(
            seen.context, "Session summary:\ngoal: retries\n\nRecent turns:\nAssistant: plan: retries param"
        )

    def test_refresh_is_spawned_detached_when_enough_is_uncovered(self):
        self.write_transcript(("user", "add retries"), ("assistant", self.BIG))
        self.call()
        self.assertEqual(self.spawned, [("claude", SID, str(self.transcript), str(self.state), self.spawned[0][4])])
        self.assertEqual(self.spawned[0][4].get("MER_HOST"), "claude")

    def test_no_spawn_when_little_is_uncovered_or_everything_is_covered(self):
        self.write_transcript(("user", "add retries"), ("assistant", "short plan"))
        self.call()
        self.write_transcript(("user", self.BIG), ("assistant", self.BIG))
        summary.save(str(self.state), SID, "s", summary.anchor_at(read_turns(str(self.transcript), "claude"), 2))
        self.call()
        self.assertEqual(self.spawned, [])

    def test_disabled_or_off_or_guarded_does_nothing(self):
        self.write_transcript(("user", "add retries"), ("assistant", self.BIG))
        self.write_repo_config({"difficulty": {"backend": "fake"}, "context": {"enabled": False}})
        self.call()
        self.write_repo_config({"difficulty": {"backend": "fake"}, "router": {"mode": "off"}})
        self.call()
        self.write_repo_config({"difficulty": {"backend": "fake"}})
        self.call(env_extra={GUARD_ENV: "1"})
        self.assertEqual(self.spawned, [])
        self.assertTrue(all(i.context == "" for i in FakeBackend.inputs))

    def test_missing_or_unreadable_transcript_falls_back_to_the_prompt_alone(self):
        self.call(path=self.root / "missing.jsonl")
        self.call(host="opencode")
        self.assertEqual([i.context for i in FakeBackend.inputs], ["", ""])
        self.assertEqual(self.spawned, [])

    def test_a_failing_spawner_never_breaks_routing(self):
        self.write_transcript(("user", "add retries"), ("assistant", self.BIG))

        def boom(*args):
            raise OSError("cannot spawn")

        out = self.call(spawn=boom)
        self.assertIn("fix →", json.loads(out)["hookSpecificOutput"]["additionalContext"])

    def test_codex_gets_context_and_a_background_refresh_when_due(self):
        rows = [
            {
                "type": "response_item",
                "payload": {"type": "message", "role": role, "content": [{"type": kind, "text": text}]},
            }
            for role, kind, text in (("user", "input_text", "add retries"), ("assistant", "output_text", self.BIG))
        ]
        self.transcript.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        self.call(host="codex")
        self.assertIn("Assistant: " + "B" * 100, FakeBackend.inputs[0].context)
        self.assertEqual([args[:4] for args in self.spawned], [("codex", SID, str(self.transcript), str(self.state))])

    def test_codex_refresh_is_not_spawned_on_an_unverified_version(self):
        rows = [
            {
                "type": "response_item",
                "payload": {"type": "message", "role": role, "content": [{"type": kind, "text": text}]},
            }
            for role, kind, text in (("user", "input_text", "add retries"), ("assistant", "output_text", self.BIG))
        ]
        self.transcript.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        for version in ("0.159.0", None):
            self.call(host="codex", version=version)
        self.assertEqual(self.spawned, [])
        self.assertIn("Assistant: " + "B" * 100, FakeBackend.inputs[-1].context)  # raw recent turns still flow
        self.write_transcript(("user", "add retries"), ("assistant", self.BIG))
        self.call(host="claude", version=None)  # Claude does not depend on the Codex version
        self.assertEqual(len(self.spawned), 1)

    def test_max_chars_bounds_the_context(self):
        self.write_transcript(("user", "add retries"), ("assistant", "x" * 5000), ("user", "진행"))
        self.write_repo_config({"difficulty": {"backend": "fake"}, "context": {"max_chars": 600}})
        self.call()
        self.assertLessEqual(len(FakeBackend.inputs[0].context), 600)


if __name__ == "__main__":
    unittest.main()

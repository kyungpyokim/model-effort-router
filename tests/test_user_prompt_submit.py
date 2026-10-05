import json
import unittest
from unittest.mock import patch

from model_effort_router.host import codex_hooks
from tests.hook_helpers import DEV, HookCase, run_script


class UserPromptSubmitTest(HookCase):
    def ctx(self, proc):
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(set(out), {"hookSpecificOutput"})  # exact shape; nothing that could block or deny
        self.assertEqual(set(out["hookSpecificOutput"]), {"hookEventName", "additionalContext"})
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        return out["hookSpecificOutput"]["additionalContext"]

    def silent(self, proc):
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))

    def test_recursion_guard_is_noop(self):
        self.silent(self.submit(env_extra={"MER_CLASSIFIER": "1"}))
        self.assertFalse(self.state.exists())

    def test_no_route_gets_no_context_and_no_log(self):
        self.silent(self.submit("What is the capital of France?"))
        self.assertEqual(self.log_events(), [])

    def test_host_generated_messages_are_never_classified(self):
        for prompt in ('Another Claude session sent a message:\n<agent-message from="a1">Fix the bug in auth.py</agent-message>',
                       "<task-notification>\n<task-id>b1</task-id> refactor the payment module</task-notification>",
                       "[SYSTEM NOTIFICATION - NOT USER INPUT]\n<task-notification>fix it</task-notification>",
                       "<bash-input>python3 -m evaluation.live_runner --live</bash-input>",
                       "<command-name>/compact</command-name>"):
            self.silent(self.submit(prompt))
        self.assertEqual(self.log_events(), [])  # no backend call, nothing logged
        self.ctx(self.submit("Please fix <agent-message> parsing in parser.py"))  # a real request mentioning the tag

    def test_no_route_stays_silent_even_with_a_rejected_override(self):
        self.silent(self.submit("/router bogus=1\nWhat is the capital of France?"))

    def test_off_override_and_off_config_are_silent(self):
        self.silent(self.submit("/router off\n" + DEV))
        self.write_repo_config({"router": {"mode": "off"}, "difficulty": {"backend": "fake"}})
        self.silent(self.submit())

    def test_rejected_override_on_a_routed_prompt_adds_a_note(self):
        self.assertIn("not understood", self.ctx(self.submit("/router bogus=1\n" + DEV)))

    def test_l3_advice_has_level_flags_and_recommended_setting_only(self):
        self.fake = {"level": "L3", "confidence": 0.6}
        c = self.ctx(self.submit())
        self.assertIn("Advisory only", c)
        self.assertIn("Difficulty: L3 (confidence 0.60). Risk flags: none.", c)
        self.assertIn("Recommended session: gpt-6-luna, reasoning effort high; switch with /model if you want.", c)
        for absent in ("Plan first", "independent review"):
            self.assertNotIn(absent, c)

    def test_l1_recommendation(self):
        self.fake = {"level": "L1"}
        self.assertIn("gpt-6-luna, reasoning effort medium", self.ctx(self.submit()))

    def test_l4_advises_plan_first_and_independent_review_with_exact_mer_commands(self):
        self.fake = {"level": "L4"}
        c = self.ctx(self.submit())
        self.assertIn("Recommended session: gpt-6.1-sol, reasoning effort high", c)
        self.assertIn("Plan first: write a short plan", c)
        self.assertIn("independent review (gpt-6.1-sol, reasoning effort high)", c)
        mer = f'python3 {self.plugin_root() / "bin" / "mer"} run'
        self.assertIn(f"`{mer} --review-profile frontier:high 'review only: check the current diff for <the task>'`", c)
        self.assertIn(f"`{mer} '<the task>'`", c)
        self.assertIn("Single-quote the request", c)  # no shell expansion of task text

    def test_review_advice_carries_the_risk_floor(self):
        self.fake = {"level": "L4", "risk_flags": ["data_loss"]}
        self.assertIn("--review-profile frontier:xhigh", self.ctx(self.submit()))

    def test_auth_flag_adds_review_advice_even_at_low_level(self):
        self.fake = {"level": "L2", "risk_flags": ["auth"]}
        c = self.ctx(self.submit())
        self.assertIn("Risk flags: auth.", c)
        self.assertIn("Plan first", c)
        self.assertIn("independent review", c)
        self.assertIn("gpt-6-luna, reasoning effort medium", c)  # risk never moves the session recommendation

    def test_flag_detected_from_the_prompt_text(self):
        self.fake = {"level": "L2"}
        c = self.ctx(self.submit("Fix the password reset login in auth.py"))
        self.assertIn("Risk flags: auth", c)
        self.assertIn("independent review", c)

    def test_concurrency_only_has_no_review_advice(self):
        self.fake = {"level": "L2", "risk_flags": ["concurrency"]}
        c = self.ctx(self.submit())
        self.assertNotIn("independent review", c)
        self.assertNotIn("Plan first", c)

    def test_never_mentions_spawning_or_stage_protocol(self):
        for level in ("L1", "L3", "L5"):
            self.fake = {"level": level, "risk_flags": ["auth"]}
            c = self.ctx(self.submit()).lower()
            for banned in ("spawn_agent", "task_name", "mer_plan", "mer_implement", "fork_turns", "deny", "--session"):
                self.assertNotIn(banned, c)

    def test_plan_only_and_review_only_targets(self):
        self.fake = {"level": "L3"}
        c = self.ctx(self.submit("Write a plan to refactor parser.py, plan only"))
        self.assertIn("Recommended for planning: gpt-6.1-sol, reasoning effort high", c)
        self.assertNotIn("Recommended session", c)
        c = self.ctx(self.submit("review only: check the changes in parser.py"))
        self.assertIn("Recommended for this review: gpt-6.1-sol, reasoning effort high", c)

    def test_session_override_shapes_the_recommendation(self):
        self.fake = {"level": "L1"}
        self.assertIn("gpt-6.1-sol, reasoning effort xhigh", self.ctx(self.submit("/router session=frontier:xhigh\n" + DEV)))

    def test_backend_failure_still_advises_from_the_default_level_and_logs_it(self):
        self.fake = {"raise": True}
        self.assertIn("Difficulty: L3", self.ctx(self.submit()))
        (ev,) = [e for e in self.log_events() if e["event"] == "route"]
        self.assertEqual((ev["decision"]["backend"], ev["fallback"]), ("default", True))

    def test_bad_config_is_fail_open_with_error_logged(self):
        (self.repo / ".model-effort-router.json").write_text("{not json")
        self.silent(self.submit())
        errs = [e for e in self.log_events() if e["event"] == "error"]
        self.assertEqual(len(errs), 1)
        self.assertNotIn("ZEBRA_SECRET_PROMPT", json.dumps(errs))

    def test_garbage_stdin_is_fail_open(self):
        self.silent(run_script("hooks/user_prompt_submit.py", stdin="not json", env=self.env()))
        self.assertTrue(self.log_file("_errors").exists())

    def test_log_holds_only_hash_and_length_and_nothing_else_is_written(self):
        self.submit()
        (ev,) = [e for e in self.log_events() if e["event"] == "route"]
        self.assertEqual((ev["target"], ev["decision"]["level"], ev["decision"]["backend"], ev["fallback"]),
                         ("route", "L3", "fake", False))
        self.assertEqual((ev["prompt_len"], len(ev["prompt_sha"])), (len(DEV), 12))
        self.assertIsInstance(ev["latency_ms"], (int, float))
        self.assertNotIn("stages", ev)
        self.assertEqual([p.suffix for p in self.state.iterdir()], [".jsonl"])  # no plan/lock state any more
        for f in self.state.iterdir():
            self.assertNotIn("ZEBRA_SECRET_PROMPT", f.read_text())

    def test_log_failure_does_not_change_the_output(self):
        blocker = self.root / "file"
        blocker.write_text("x")
        p = run_script("hooks/user_prompt_submit.py", env=self.env(MER_STATE_DIR=str(blocker / "sub")),
                       stdin=json.dumps({"session_id": "s", "cwd": str(self.repo), "prompt": DEV}))
        self.assertIn("Recommended session", self.ctx(p))

    def test_route_event_logs_classifier_usage_counts_only(self):
        self.fake = {"level": "L3", "usage": {"input_tokens": 7, "output_tokens": 2, "text": "SECRET"}}
        self.submit()
        ev = [e for e in self.log_events() if e["event"] == "route"][0]
        self.assertEqual(ev["classifier_usage"], {"input_tokens": 7, "cached_input_tokens": 0,
                                                  "output_tokens": 2, "reasoning_output_tokens": 0})

    def test_route_event_logs_classifier_usage_even_when_backend_failed(self):
        self.fake = {"raise": True, "usage": {"input_tokens": 9, "output_tokens": 1}}
        self.submit()
        ev = [e for e in self.log_events() if e["event"] == "route"][0]
        self.assertTrue(ev["fallback"])
        self.assertEqual(ev["classifier_usage"]["input_tokens"], 9)

    def test_model_backend_that_reports_nothing_logs_explicit_null(self):
        self.fake = {"level": "L3", "calls_model": True}
        self.submit()
        ev = [e for e in self.log_events() if e["event"] == "route"][0]
        self.assertIn("classifier_usage", ev)
        self.assertIsNone(ev["classifier_usage"])

    def test_rule_only_backend_has_no_classifier_usage_key(self):
        self.submit()
        self.assertNotIn("classifier_usage", [e for e in self.log_events() if e["event"] == "route"][0])

    def test_user_config_used_when_repo_has_none_and_repo_beats_user(self):
        (self.repo / ".model-effort-router.json").unlink()
        cfg = self.home / "user.json"
        cfg.write_text(json.dumps({"router": {"mode": "off"}}))
        self.silent(self.submit(env_extra={"MER_USER_CONFIG": str(cfg)}))
        self.write_repo_config({"router": {"mode": "auto"}, "difficulty": {"backend": "fake"}})
        self.assertIn("Recommended session", self.ctx(self.submit(env_extra={"MER_USER_CONFIG": str(cfg)})))

    def test_backend_target_route_advises_a_prompt_the_rules_would_skip(self):
        prompt = "Bump the base image in the Dockerfile to python 3.12"
        self.fake = {"level": "L2"}
        self.silent(self.submit(prompt))  # no target from the backend: rules say no_route, no call, no log
        self.assertEqual(self.log_events(), [])
        self.fake = {"level": "L2", "target": "route"}
        self.assertIn("Recommended session", self.ctx(self.submit(prompt)))
        (ev,) = [e for e in self.log_events() if e["event"] == "route"]
        self.assertEqual((ev["target"], ev["target_source"]), ("route", "backend"))

    def test_backend_no_route_is_silent_but_logs_target_and_classifier_spend_without_text(self):
        self.fake = {"level": "L2", "target": "no_route", "usage": {"input_tokens": 541, "output_tokens": 12}}
        self.silent(self.submit("Fix the bug in parser.py ZEBRA_SECRET_PROMPT"))
        (ev,) = [e for e in self.log_events() if e["event"] == "route"]
        self.assertEqual((ev["target"], ev["target_source"], ev["classifier_usage"]["input_tokens"]), ("no_route", "backend", 541))
        self.assertNotIn("ZEBRA_SECRET_PROMPT", json.dumps(ev))

    def test_rules_target_source_is_logged_for_backends_without_a_target(self):
        self.submit()
        (ev,) = [e for e in self.log_events() if e["event"] == "route"]
        self.assertEqual(ev["target_source"], "rules")

    def test_backend_failure_falls_back_to_rules_target(self):
        self.fake = {"raise": True, "target": "no_route"}
        self.assertIn("Recommended session", self.ctx(self.submit()))  # default decision has no target: rules say route

    def test_unicode_prompt(self):
        self.assertIn("Recommended session", self.ctx(self.submit("파일 parser.py 버그 수정 🚀")))

    def direct_submit(self, prompt=DEV, payload=None, applied=True):
        data = payload or {"session_id": "thread-1", "turn_id": "turn-1", "cwd": str(self.repo), "prompt": prompt}
        with patch.object(codex_hooks, "apply_turn_settings", return_value=applied) as update:
            output = codex_hooks.user_prompt_submit(data, self.env(), str(self.plugin_root()))
        return output, update

    def test_routed_targets_apply_their_selected_codex_profile(self):
        for prompt, expected in (
            (DEV, ("gpt-6-luna", "high")),
            ("Write a plan to refactor parser.py, plan only", ("gpt-6.1-sol", "high")),
            ("review only: check parser.py", ("gpt-6.1-sol", "high")),
        ):
            with self.subTest(prompt=prompt):
                output, update = self.direct_submit(prompt)
                update.assert_called_once_with("thread-1", "turn-1", *expected)
                context = json.loads(output)["hookSpecificOutput"]["additionalContext"]
                self.assertIn("Applied to this turn", context)
                self.assertNotIn("Advisory only", context)
                event = self.log_events("thread-1")[-1]
                self.assertEqual(event["turn_settings"], {"status": "applied", "model": expected[0], "effort": expected[1]})

    def test_manual_mode_applies_only_an_explicit_session_override(self):
        self.write_repo_config({"router": {"mode": "manual"}, "difficulty": {"backend": "fake"}})
        _, update = self.direct_submit("/router session=frontier:xhigh\n" + DEV)
        update.assert_called_once_with("thread-1", "turn-1", "gpt-6.1-sol", "xhigh")
        _, update = self.direct_submit(DEV)
        update.assert_not_called()

    def test_no_route_off_and_missing_turn_ids_do_not_update(self):
        for prompt, config, payload in (
            ("What is the capital of France?", None, None),
            ("/router off\n" + DEV, None, None),
            (DEV, None, {"session_id": "thread-1", "cwd": str(self.repo), "prompt": DEV}),
        ):
            with self.subTest(prompt=prompt):
                if config:
                    self.write_repo_config(config)
                _, update = self.direct_submit(prompt, payload=payload)
                update.assert_not_called()

    def test_failed_update_keeps_advisory_context_and_logs_only_profile_status(self):
        output, _ = self.direct_submit(applied=False)
        context = json.loads(output)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Advisory only", context)
        self.assertIn("Recommended session: gpt-6-luna, reasoning effort high", context)
        event = self.log_events("thread-1")[-1]
        self.assertEqual(event["turn_settings"], {"status": "unavailable", "model": "gpt-6-luna", "effort": "high"})


if __name__ == "__main__":
    unittest.main()

import json
import unittest

from tests.hook_helpers import DEV, SID, HookCase, run_script


class UserPromptSubmitTest(HookCase):
    def ctx(self, proc):
        out = json.loads(proc.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "UserPromptSubmit")
        return out["additionalContext"]

    def test_recursion_guard_is_noop(self):
        p = self.submit(env_extra={"MER_CLASSIFIER": "1"})
        self.assertEqual((p.returncode, p.stdout), (0, ""))
        self.assertFalse(self.state.exists())

    def test_no_route_is_silent(self):
        p = self.submit("What is the capital of France?")
        self.assertEqual((p.returncode, p.stdout), (0, ""))
        self.assertFalse(self.plan_file().exists())

    def test_mode_off_override_is_silent(self):
        p = self.submit("/router off\n" + DEV)
        self.assertEqual((p.returncode, p.stdout), (0, ""))

    def test_rejected_override_without_route_gives_notice(self):
        p = self.submit("/router bogus=1\nWhat is the capital of France?")
        self.assertIn("not understood", self.ctx(p))

    def test_l3_injection_has_exact_values_per_stage(self):
        c = self.ctx(self.submit())
        for line in (
            'task_name="mer_plan", fork_turns="none", model="gpt-6-sol", reasoning_effort="high"',
            'task_name="mer_implement", fork_turns="none", model="gpt-6-luna", reasoning_effort="high"',
            'task_name="mer_review", fork_turns="none", model="gpt-6-sol", reasoning_effort="high"',
        ):
            self.assertIn(line, c)
        self.assertLess(c.index("mer_plan"), c.index("mer_implement"))
        self.assertLess(c.index("mer_implement"), c.index("mer-gate"))
        self.assertLess(c.index("mer-gate"), c.index("mer_review"))
        self.assertIn(SID, c)
        self.assertIn("At most 2", c)
        self.assertIn("never", c.lower())

    def test_injection_ends_with_review_record_step(self):
        c = self.ctx(self.submit())
        self.assertIn(f"--session {SID} --review approved|changes_requested --findings", c)

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
        ev = [e for e in self.log_events() if e["event"] == "route"][0]
        self.assertNotIn("classifier_usage", ev)

    def test_l1_skips_plan_stage(self):
        self.fake = {"level": "L1"}
        c = self.ctx(self.submit())
        self.assertNotIn("mer_plan", c)
        self.assertIn('task_name="mer_implement"', c)
        self.assertIn('model="gpt-6-luna", reasoning_effort="medium"', c)

    def test_plan_only_target_has_only_plan(self):
        c = self.ctx(self.submit("Write a plan to refactor parser.py, plan only"))
        self.assertIn("mer_plan", c)
        self.assertNotIn("mer_implement", c)
        self.assertNotIn("mer_review", c)

    def test_state_persisted_and_atomic_leftovers_absent(self):
        self.submit()
        st = self.plan_state()
        self.assertEqual(st["stages"]["plan"]["model"], "gpt-6-sol")
        self.assertEqual(st["stages"]["implement"]["effort"], "high")
        self.assertEqual(st["stages"]["review"]["status"], "pending")
        self.assertEqual(st["fix_count"], 0)
        self.assertEqual(st["order"], ["plan", "implement", "test_gate", "review"])
        self.assertEqual([p.name for p in self.state.iterdir() if p.suffix == ".tmp"], [])

    def test_route_log_fields_and_privacy(self):
        self.submit()
        (ev,) = [e for e in self.log_events() if e["event"] == "route"]
        self.assertEqual(ev["target"], "route")
        self.assertEqual(ev["decision"]["level"], "L3")
        self.assertEqual(ev["decision"]["backend"], "fake")
        self.assertFalse(ev["fallback"])
        self.assertIsInstance(ev["latency_ms"], (int, float))
        self.assertIn("level_default", ev["applied_rules"])
        plan = [s for s in ev["stages"] if s["stage"] == "plan"][0]
        self.assertEqual((plan["model"], plan["requested_effort"], plan["applied_effort"]),
                         ("gpt-6-sol", "high", "high"))
        self.assertEqual(ev["prompt_len"], len(DEV))
        self.assertEqual(len(ev["prompt_sha"]), 12)
        for f in self.state.iterdir():
            self.assertNotIn("ZEBRA_PROMPT_MARKER", f.read_text())

    def test_backend_failure_falls_back_to_default_and_logs_it(self):
        self.fake = {"raise": True}
        c = self.ctx(self.submit())
        self.assertIn("mer_implement", c)
        (ev,) = [e for e in self.log_events() if e["event"] == "route"]
        self.assertEqual(ev["decision"]["backend"], "default")
        self.assertTrue(ev["fallback"])

    def test_bad_config_is_fail_open_with_error_logged(self):
        (self.repo / ".model-effort-router.json").write_text("{not json")
        p = self.submit()
        self.assertEqual((p.returncode, p.stdout), (0, ""))
        errs = [e for e in self.log_events() if e["event"] == "error"]
        self.assertEqual(len(errs), 1)
        self.assertNotIn("ZEBRA_PROMPT_MARKER", json.dumps(errs))

    def test_garbage_stdin_is_fail_open(self):
        p = run_script("hooks/user_prompt_submit.py", stdin="not json", env=self.env())
        self.assertEqual((p.returncode, p.stdout), (0, ""))
        self.assertTrue(self.log_file("_errors").exists())

    def test_user_config_used_when_repo_has_none(self):
        (self.repo / ".model-effort-router.json").unlink()
        cfg = self.home / "user.json"
        cfg.write_text(json.dumps({"router": {"mode": "off"}}))
        p = self.submit(env_extra={"MER_USER_CONFIG": str(cfg)})
        self.assertEqual(p.stdout, "")

    def test_repo_config_beats_user_config(self):
        cfg = self.home / "user.json"
        cfg.write_text(json.dumps({"router": {"mode": "off"}}))
        self.write_repo_config({"router": {"mode": "auto"}, "difficulty": {"backend": "fake"}})
        self.assertIn("mer_implement", self.ctx(self.submit(env_extra={"MER_USER_CONFIG": str(cfg)})))

    def test_new_routed_prompt_replaces_state(self):
        self.submit()
        self.fake = {"level": "L1"}
        self.submit()
        self.assertNotIn("plan", self.plan_state()["stages"])

    def test_unicode_prompt(self):
        self.assertIn("mer_implement", self.ctx(self.submit("파일 parser.py 버그 수정 🚀")))


if __name__ == "__main__":
    unittest.main()

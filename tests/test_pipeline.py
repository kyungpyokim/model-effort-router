import contextlib
import dataclasses
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pipeline  # noqa: E402
import router  # noqa: E402

FAKE_CODEX = """#!{python}
import json, os, pathlib, sys
argv = sys.argv[1:]
text = " ".join(argv)
role = next((name for marker, name in (
    ("merged verification", "review"), ("fix stage", "fix"),
    ("planning stage", "plan"),
) if marker in text), "execute")
directory = pathlib.Path(os.environ["FAKE_DIR"])
index = int((directory / "count").read_text()) if (directory / "count").exists() else 0
(directory / "count").write_text(str(index + 1))
with (directory / "calls.jsonl").open("a") as stream:
    stream.write(json.dumps({{"role": role, "model": argv[argv.index("-m") + 1], "effort": [a for a in argv if a.startswith("model_reasoning_effort=")], "text": text}}) + chr(10))
replies = json.loads((directory / "replies.json").read_text())
reply = replies[index] if index < len(replies) else {{}}
if reply.get("touch"):
    pathlib.Path(reply["touch"]).write_text("x")
if role == "plan" and not reply.get("no_plan"):
    import re
    plan = re.search(r"exactly: (\\S+)", text)
    pathlib.Path(plan.group(1)).write_text("{{}}")
print(reply.get("out", ""))
sys.exit(reply.get("rc", 0))
"""


class PipelineCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        fake = self.dir / "codex"
        fake.write_text(FAKE_CODEX.format(python=sys.executable), encoding="utf-8")
        fake.chmod(0o755)
        self.work = self.dir / "work"
        self.work.mkdir()
        old_path, old_dir = os.environ.get("PATH"), os.environ.get("FAKE_DIR")
        os.environ["PATH"] = f"{self.dir}{os.pathsep}{old_path}"
        os.environ["FAKE_DIR"] = str(self.dir)
        self.addCleanup(os.environ.__setitem__, "PATH", old_path)
        self.addCleanup(lambda: os.environ.pop("FAKE_DIR") if old_dir is None else os.environ.__setitem__("FAKE_DIR", old_dir))

    def payload(self, level="L4", task_type="implementation", platform="codex", critical=False):
        config = router.load_config(ROOT / "config" / "model-map.json")
        result = router.route("do the thing", platform, config, level, task_type, critical=critical)
        return router.result_payload(result, router.stage_commands(result, "do the thing"), "do the thing")

    def run_pipeline(self, replies, payload=None, tests=()):
        (self.dir / "replies.json").write_text(json.dumps(replies), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = pipeline.run_route(payload or self.payload(), list(tests), str(self.work))
        calls = [json.loads(line) for line in (self.dir / "calls.jsonl").read_text().splitlines()] if (self.dir / "calls.jsonl").exists() else []
        return rc, calls

    def roles(self, calls):
        return [call["role"] for call in calls]


class PipelineRunTests(PipelineCase):
    def test_green_run_ends_with_one_sol_review_at_high_effort(self):
        rc, calls = self.run_pipeline([{}, {"out": "no findings\nVERDICT: PASS"}])
        self.assertEqual(rc, 0)
        self.assertEqual(self.roles(calls), ["execute", "review"])
        self.assertEqual(calls[1]["model"], "gpt-5.6-sol")
        self.assertIn("model_reasoning_effort=high", calls[1]["effort"])
        self.assertNotEqual(calls[0]["model"], "gpt-5.6-sol")

    def test_failing_test_goes_to_the_implementer_with_a_log_tail_not_to_a_judge(self):
        flag = self.work / "flag"
        rc, calls = self.run_pipeline(
            [{}, {"touch": str(flag)}, {"out": "VERDICT: PASS"}], tests=[f"echo boom >&2; test -f {flag}"]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(self.roles(calls), ["execute", "fix", "review"])
        self.assertIn("(exit 1)", calls[1]["text"])
        self.assertIn("boom", calls[1]["text"])
        self.assertNotEqual(calls[1]["model"], "gpt-5.6-sol")
        self.assertIn("PASS: ", calls[2]["text"])

    def test_tests_that_never_pass_fix_twice_then_replan_once_then_stop(self):
        rc, calls = self.run_pipeline([{}] * 8, tests=["false"])
        self.assertEqual(rc, pipeline.EXIT_GAVE_UP)
        self.assertEqual(self.roles(calls), ["execute", "fix", "fix", "plan", "execute", "fix", "fix"])
        self.assertEqual(calls[3]["model"], "gpt-5.6-sol")
        self.assertNotIn("review", self.roles(calls))

    def test_review_fail_is_fixed_once_then_re_reviewed(self):
        rc, calls = self.run_pipeline([{}, {"out": "null deref\nVERDICT: FAIL"}, {}, {"out": "VERDICT: PASS"}])
        self.assertEqual(rc, 0)
        self.assertEqual(self.roles(calls), ["execute", "review", "fix", "review"])
        self.assertIn("null deref", calls[2]["text"])
        self.assertNotEqual(calls[2]["model"], "gpt-5.6-sol")

    def test_second_review_fail_replans_with_the_planning_model(self):
        fail = {"out": "VERDICT: FAIL"}
        rc, calls = self.run_pipeline([{}, fail, {}, fail, {}, {}, {"out": "VERDICT: PASS"}])
        self.assertEqual(rc, 0)
        self.assertEqual(self.roles(calls), ["execute", "review", "fix", "review", "plan", "execute", "review"])
        self.assertEqual(calls[4]["model"], "gpt-5.6-sol")

    def test_review_fails_are_capped(self):
        fail = {"out": "VERDICT: FAIL"}
        rc, calls = self.run_pipeline([{}, fail, {}, fail, {}, {}, fail, {}, fail, {}])
        self.assertEqual(rc, pipeline.EXIT_GAVE_UP)
        self.assertEqual(self.roles(calls).count("plan"), 1)
        self.assertEqual(self.roles(calls).count("review"), 4)

    def test_a_review_without_a_verdict_stops_instead_of_passing(self):
        rc, calls = self.run_pipeline([{}, {"out": "looks fine to me"}])
        self.assertEqual(rc, pipeline.EXIT_NO_VERDICT)
        self.assertEqual(self.roles(calls), ["execute", "review"])

    def test_implementer_escalation_evidence_triggers_a_replan(self):
        rc, calls = self.run_pipeline([{"out": "ESCALATE: public API change needed"}, {}, {}, {"out": "VERDICT: PASS"}])
        self.assertEqual(rc, 0)
        self.assertEqual(self.roles(calls), ["execute", "plan", "execute", "review"])
        self.assertIn("public API change needed", calls[1]["text"])

    def test_a_failing_stage_stops_the_run_with_its_exit_code(self):
        rc, calls = self.run_pipeline([{"rc": 7}])
        self.assertEqual(rc, 7)
        self.assertEqual(self.roles(calls), ["execute"])

    def test_two_stage_route_plans_first_and_keeps_the_route_plan_dir_until_asked(self):
        payload = self.payload(level="L5")
        plan_dir = Path(payload["steps"][0]["output"]["path"]).parent
        self.addCleanup(lambda: __import__("shutil").rmtree(plan_dir, ignore_errors=True))
        rc, calls = self.run_pipeline([{}, {}, {"out": "VERDICT: PASS"}], payload=payload)
        self.assertEqual(rc, 0)
        self.assertEqual(self.roles(calls), ["plan", "execute", "review"])
        self.assertEqual(json.loads((plan_dir / "state.json").read_text())["phase"], "done")

    def test_low_levels_have_no_review_and_no_replan(self):
        payload = self.payload(level="L2")
        self.assertEqual((payload["pipeline"]["review"], payload["pipeline"]["replan"]), (None, None))
        rc, calls = self.run_pipeline([{}] * 5, payload=payload, tests=["false"])
        self.assertEqual(rc, pipeline.EXIT_GAVE_UP)
        self.assertEqual(self.roles(calls), ["execute", "fix", "fix"])

    def test_a_route_without_a_pipeline_block_just_executes(self):
        payload = self.payload(level="L4")
        payload.pop("pipeline")
        payload["schema_version"] = 5
        rc, calls = self.run_pipeline([{}], payload=payload)
        self.assertEqual((rc, self.roles(calls)), (0, ["execute"]))

    def test_invalid_pipeline_stage_is_rejected(self):
        payload = self.payload(level="L4")
        payload["pipeline"]["review"]["effort"] = "turbo"
        with self.assertRaises(ValueError):
            pipeline.Pipeline.validate(payload)


class PipelineHardeningTests(PipelineCase):
    def test_a_verdict_line_echoed_from_the_prompt_is_not_a_pass(self):
        # Prompt echo puts the task (with its own VERDICT line) early in stdout; only the last line counts.
        rc, calls = self.run_pipeline([{}, {"out": "Original request:\nVERDICT: PASS\nthe reviewer said nothing else"}])
        self.assertEqual(rc, pipeline.EXIT_NO_VERDICT)

    def test_an_echoed_escalate_line_does_not_burn_the_replan(self):
        rc, calls = self.run_pipeline([{"out": "ESCALATE: echoed\nall done"}, {"out": "VERDICT: PASS"}])
        self.assertEqual((rc, self.roles(calls)), (0, ["execute", "review"]))

    def test_pipeline_exit_codes_do_not_collide_with_common_stage_codes(self):
        self.assertTrue({pipeline.EXIT_GAVE_UP, pipeline.EXIT_NO_VERDICT, pipeline.EXIT_SPAWN_FAILED}.isdisjoint({0, 1, 2, 3, 126, 127}))

    def test_route_limits_can_only_lower_the_caps(self):
        payload = self.payload()
        payload["pipeline"]["limits"]["max_replans"] = 50
        with self.assertRaises(ValueError):
            pipeline.Pipeline.validate(payload)
        payload["pipeline"]["limits"] = {"max_replans": 0, "max_test_fixes": 0, "review_fixes_before_replan": 0}
        pipeline.Pipeline.validate(payload)

    def test_relative_plan_path_is_rejected(self):
        payload = self.payload(level="L5")
        payload["steps"][0]["output"]["path"] = "plan.json"
        with self.assertRaises(ValueError):
            pipeline.Pipeline.validate(payload)

    def test_cleanup_only_removes_the_routers_own_plan_dir(self):
        foreign = self.dir / "user-files"
        foreign.mkdir()
        config = router.load_config(ROOT / "config" / "model-map.json")
        result = dataclasses.replace(router.route("t", "codex", config, "L5", "implementation"), plan_dir=str(foreign))
        payload = router.result_payload(result, router.stage_commands(result, "t"), "t")
        rc, _ = self.run_pipeline([{}, {}, {"out": "VERDICT: PASS"}], payload=payload)
        self.assertEqual(rc, 0)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            pipeline.run_route(payload, [], str(self.work), cleanup=True)
        self.assertTrue(foreign.exists())

    def test_interactive_shapes_are_detected(self):
        self.assertTrue(pipeline.is_interactive(["codex", "-m", "x", "task"]))
        self.assertFalse(pipeline.is_interactive(["codex", "exec", "-m", "x", "task"]))
        self.assertTrue(pipeline.is_interactive(["claude", "--model", "m", "task"]))
        self.assertFalse(pipeline.is_interactive(["claude", "-p", "--model", "m", "task"]))
        self.assertTrue(pipeline.is_interactive(["agy", "--model", "m", "--prompt-interactive", "t"]))
        self.assertFalse(pipeline.is_interactive(["agy", "--model", "m", "--prompt", "t"]))

    def test_stored_interactive_route_keeps_the_terminal(self):
        config = router.load_config(ROOT / "config" / "model-map.json")
        result = router.route("t", "codex", config, "L2", "implementation")
        payload = router.result_payload(result, router.stage_commands(result, "t", interactive=True), "t")
        route_file = self.dir / "route.json"
        route_file.write_text(json.dumps(payload), encoding="utf-8")
        (self.dir / "replies.json").write_text("[{}]", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = pipeline.main(["--route-file", str(route_file)])
        self.assertEqual(rc, 0)
        calls = [json.loads(line) for line in (self.dir / "calls.jsonl").read_text().splitlines()]
        self.assertEqual(len(calls), 1)
        self.assertFalse((self.work / "state.json").exists())


class PipelineFailClosedTests(PipelineCase):
    def git_repo(self):
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        (self.work / "a.txt").write_text("a")
        for args in (["init", "-q"], ["add", "."], ["commit", "-qm", "init"]):
            subprocess.run(["git", *args], cwd=self.work, env=env, check=True, capture_output=True)

    def test_an_implementer_that_changed_nothing_fails_review_without_a_reviewer_call(self):
        self.git_repo()
        rc, calls = self.run_pipeline([{}, {}, {}, {}, {}, {}, {}, {}])
        self.assertEqual(rc, pipeline.EXIT_GAVE_UP)
        self.assertNotIn("review", self.roles(calls))
        self.assertEqual(self.roles(calls)[:3], ["execute", "fix", "plan"])

    def test_a_real_change_reaches_the_reviewer_with_its_diff(self):
        self.git_repo()
        rc, calls = self.run_pipeline([{"touch": str(self.work / "a.txt")}, {"out": "VERDICT: PASS"}])
        self.assertEqual(rc, 0)
        self.assertEqual(self.roles(calls), ["execute", "review"])

    def test_a_planner_that_wrote_no_plan_stops_the_run(self):
        payload = self.payload(level="L5")
        plan_dir = Path(payload["steps"][0]["output"]["path"]).parent
        self.addCleanup(lambda: __import__("shutil").rmtree(plan_dir, ignore_errors=True))
        rc, calls = self.run_pipeline([{"no_plan": True}], payload=payload)
        self.assertEqual(rc, pipeline.EXIT_NO_PLAN)
        self.assertEqual(self.roles(calls), ["plan"])

    def test_stage_logs_are_phase_based_and_hide_the_command_unless_verbose(self):
        (self.dir / "replies.json").write_text(json.dumps([{}, {"out": "VERDICT: PASS"}]), encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            pipeline.run_route(self.payload(), [], str(self.work))
        text = err.getvalue()
        self.assertIn("phase=implement model=gpt-5.6-terra effort=high", text)
        self.assertIn("phase=review model=gpt-5.6-sol effort=high attempt=1", text)
        self.assertNotIn("command:", text)


class ClaudeAccessTests(unittest.TestCase):
    def commands(self, level="L5", critical=False):
        config = router.load_config(ROOT / "config" / "model-map.json")
        result = router.route("t", "claude-code", config, level, "implementation", critical=critical)
        return router.stage_commands(result, "t")

    def test_only_implement_and_fix_stages_may_edit(self):
        planner, implementer = self.commands()
        self.assertIn("acceptEdits", implementer)
        self.assertNotIn("acceptEdits", planner)
        self.assertEqual(planner[planner.index("--permission-mode") + 1], "dontAsk")
        self.assertTrue(any(arg.startswith("Edit(//") and arg.endswith("plan.json)") for arg in planner))
        review = router.stage_command("claude-code", {"model": "claude-opus-5", "effort": "high"}, "i", "p", "read")
        self.assertEqual(review[review.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(review[review.index("--disallowedTools") + 1], "Edit")
        self.assertNotIn("acceptEdits", review)
        for command in (planner, implementer, review):
            self.assertEqual(command[-2], "--")
            self.assertNotIn("--dangerously-skip-permissions", command)

    def test_single_stage_judges_are_read_only_and_implementers_edit(self):
        config = router.load_config(ROOT / "config" / "model-map.json")
        for task_type, expected in (("implementation", "acceptEdits"), ("design", "dontAsk"), ("review", "dontAsk")):
            with self.subTest(task_type=task_type):
                result = router.route("t", "claude-code", config, "L3", task_type)
                command = router.shell_command(result, "t", False)
                self.assertEqual(command[command.index("--permission-mode") + 1], expected)

    def test_interactive_claude_keeps_its_own_permission_prompts(self):
        config = router.load_config(ROOT / "config" / "model-map.json")
        result = router.route("t", "claude-code", config, "L3", "implementation")
        self.assertNotIn("--permission-mode", router.shell_command(result, "t", True))


class RouteFileArgvGrammarTests(unittest.TestCase):
    def test_every_generated_command_passes_the_grammar(self):
        config = router.load_config(ROOT / "config" / "model-map.json")
        for platform in ("codex", "claude-code", "antigravity"):
            for level in router.LEVELS:
                for task_type in router.TASK_TYPES:
                    result = router.route("t", platform, config, level, task_type)
                    for interactive in (False, True):
                        if interactive and result.mode == "two_stage":
                            continue
                        for command in router.stage_commands(result, "t", interactive):
                            router.validate_argv(platform, command)

    def test_smuggled_flags_are_rejected(self):
        bad = {
            "codex": (
                ["codex", "exec", "-m", "gpt-5.6-sol", "-c", "sandbox_mode=danger-full-access", "task"],
                ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "-m", "gpt-5.6-sol", "task"],
                ["codex", "exec", "-m", "gpt-5.6-sol", "-c", "model_reasoning_effort=turbo", "task"],
                ["codex", "exec", "task"],
            ),
            "claude-code": (
                ["claude", "-p", "--model", "claude-opus-5", "--dangerously-skip-permissions", "--", "task"],
                ["claude", "-p", "--model", "claude-opus-5", "--permission-mode", "bypassPermissions", "--", "task"],
                ["claude", "-p", "--model", "claude-opus-5", "--allowedTools", "Bash", "--", "task"],
                ["claude", "-p", "--model", "claude-opus-5", "--allowedTools", "Edit(/etc/passwd)", "--", "task"],
                ["claude", "-p", "--model", "claude-opus-5", "--add-dir", "/", "--", "task"],
                ["claude", "-p", "--", "task"],
            ),
            "antigravity": (
                ["agy", "--model", "Gemini 3.1 Pro (High)", "--yolo", "--prompt", "task"],
                ["agy", "--model", "Gemini 3.1 Pro (High)", "--prompt"],
            ),
        }
        for platform, commands in bad.items():
            for command in commands:
                with self.subTest(command=command), self.assertRaises(ValueError):
                    router.validate_argv(platform, command)

    def test_replaying_a_route_with_an_injected_flag_is_refused(self):
        config = router.load_config(ROOT / "config" / "model-map.json")
        result = router.route("t", "claude-code", config, "L2", "implementation")
        payload = router.result_payload(result, router.stage_commands(result, "t"), "t")
        payload["steps"][0]["command"].insert(-2, "--dangerously-skip-permissions")
        with tempfile.TemporaryDirectory() as tmp:
            route_file = Path(tmp) / "route.json"
            route_file.write_text(json.dumps(payload), encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(router.main(["--route-file", str(route_file)]), 2)
                self.assertEqual(pipeline.main(["--route-file", str(route_file)]), 2)
            self.assertIn("router-generated", err.getvalue())


class PipelinePlanTests(unittest.TestCase):
    def payload(self, platform, level="L4", task_type="implementation", critical=False):
        config = router.load_config(ROOT / "config" / "model-map.json")
        result = router.route("t", platform, config, level, task_type, critical=critical)
        return router.result_payload(result, router.stage_commands(result, "t"), "t")

    def test_risk_tier_raises_the_review_and_replan_effort_but_not_the_implementer(self):
        for tier, effort in (("standard", "high"), ("critical", "max")):
            with self.subTest(tier=tier):
                payload = self.payload("codex", critical=tier == "critical")
                pipe = payload["pipeline"]
                self.assertEqual((pipe["review"]["effort"], pipe["replan"]["effort"]), (effort, effort))
                self.assertEqual(payload["steps"][-1]["effort"], "high")
                self.assertEqual(payload["steps"][-1]["model"], "gpt-5.6-terra")

    def test_claude_review_is_opus_and_carries_the_agent_delegation(self):
        payload = self.payload("claude-code", critical=True)
        review = payload["pipeline"]["review"]
        self.assertEqual((review["model"], review["effort"]), ("claude-opus-5", "max"))
        self.assertEqual(review["agent"]["subagent_type"], "model-effort:effort-max")

    def test_two_stage_replan_reuses_the_route_planner(self):
        payload = self.payload("codex", level="L5")
        self.assertEqual(payload["pipeline"]["replan"]["model"], payload["steps"][0]["model"])

    def test_judging_task_types_have_no_pipeline(self):
        for task_type in ("design", "review"):
            self.assertIsNone(self.payload("codex", task_type=task_type)["pipeline"])

    def test_pipeline_records_the_task_but_no_execution_state(self):
        pipe = self.payload("codex")["pipeline"]
        self.assertEqual(pipe["task"], "t")
        self.assertFalse({"phase", "review_attempt", "attempt"} & set(pipe))


if __name__ == "__main__":
    unittest.main()

import io
import tempfile
import unittest
from unittest.mock import patch

import model_effort_router.cli as cli
from model_effort_router.flow import WorkerInterrupted, run_low_first
from model_effort_router.host import hosts
from model_effort_router.policy.router import route


class LowFirstTests(unittest.TestCase):
    def _plan(self, role="fix"):
        return route("implement this", explicit=True, role_override=role, effort_override="low")

    @staticmethod
    def _worker_result(plan, usage=None):
        usage = {"input": 0, "cached_input": 0, "output": 0, "reasoning_output": 0} if usage is None else usage
        return {"message": "done", "model": plan.model, "requested_effort": plan.requested_effort,
                "applied_effort": plan.applied_effort, "usage": usage}

    def _run(self, *, plan=None, verify=None, retry_low=False, approve_xhigh=False, start_effort="low", side_effect=None):
        def worker(_task, selected_plan, **_kwargs):
            if side_effect:
                return side_effect(selected_plan)
            return self._worker_result(selected_plan)
        with patch("model_effort_router.flow.run_worker", side_effect=worker):
            return run_low_first(
                "implement this", plan or self._plan(), cwd="/tmp", runner=lambda *_a, **_k: None,
                env={}, host=hosts.CODEX, timeout_s=10,
                verify=verify or (lambda *_a: {"status": "passed", "exit_code": 0}),
                retry_low=retry_low, approve_xhigh=approve_xhigh, start_effort=start_effort,
            )

    def test_promotes_with_failure_packet_then_stops_on_pass(self):
        calls, packets = [], []

        def worker(task, plan, **kwargs):
            calls.append(plan.requested_effort)
            packets.append(kwargs["context_packet"])
            return self._worker_result(plan, {"input": 3, "cached_input": 1, "output": 2,
                                              "reasoning_output": 0})

        checks = iter((
            {"status": "failed", "exit_code": 1, "output_tail": "AssertionError"},
            {"status": "passed", "exit_code": 0},
        ))
        with patch("model_effort_router.flow.run_worker", side_effect=worker):
            result = run_low_first("implement this", self._plan(), cwd="/tmp", runner=lambda *_a, **_k: None,
                                   env={}, host=hosts.CODEX, timeout_s=10, verify=lambda *_a: next(checks))

        self.assertEqual(calls, ["low", "medium"])
        self.assertIn("AssertionError", packets[1])
        self.assertEqual((result["status"], result["first_pass"], result["escalation_count"]),
                         ("complete", False, 1))
        self.assertEqual(result["usage"], {"input": 6, "cached_input": 2, "output": 4, "reasoning_output": 0})
        self.assertEqual(result["usage_missing"], 0)

    def test_optional_low_retry_precedes_medium_and_does_not_count_as_escalation(self):
        efforts = []
        checks = iter(({"status": "failed", "exit_code": 1}, {"status": "failed", "exit_code": 1},
                       {"status": "passed", "exit_code": 0}))

        def worker(_task, selected_plan, **_kwargs):
            efforts.append(selected_plan.requested_effort)
            return {**self._worker_result(selected_plan), "usage": None}

        result = self._run(verify=lambda *_a: next(checks), retry_low=True,
                           side_effect=lambda plan: worker(None, plan))

        self.assertEqual(efforts, ["low", "low", "medium"])
        self.assertEqual(result["escalation_count"], 1)
        self.assertEqual(result["usage_missing"], 3)

    def test_uses_module_worker(self):
        with patch("model_effort_router.flow.run_worker", side_effect=lambda _t, plan, **_k: self._worker_result(plan)) as worker:
            result = run_low_first("implement this", self._plan(), cwd="/tmp", runner=lambda *_a, **_k: None,
                                   env={}, host=hosts.CODEX, timeout_s=10,
                                   verify=lambda *_a: {"status": "passed", "exit_code": 0})
        self.assertEqual(worker.call_count, 1)
        self.assertEqual(result["status"], "complete")

    def test_worker_interruption_propagates_with_partial_result(self):
        with patch("model_effort_router.flow.run_worker", side_effect=WorkerInterrupted("stop")):
            with self.assertRaises(WorkerInterrupted) as raised:
                run_low_first("implement this", self._plan(), cwd="/tmp", runner=lambda *_a, **_k: None,
                              env={}, host=hosts.CODEX, timeout_s=10,
                              verify=lambda *_a: {"status": "passed", "exit_code": 0})
        self.assertEqual(raised.exception.result["status"], "error")

    def test_verification_timeout_or_invalid_result_is_an_error(self):
        for check in (
            {"status": "failed", "exit_code": 1, "reason": "timeout"},
            {"status": "not_run", "exit_code": None, "reason": "start error"},
            {"status": "wat"},
        ):
            with self.subTest(check=check):
                calls = []
                result = self._run(side_effect=lambda plan: calls.append(1) or self._worker_result(plan),
                                   verify=lambda *_a, check=check: check)
                self.assertEqual((result["status"], len(calls)), ("error", 1))

    def test_verification_exception_is_an_error_without_promotion(self):
        calls = []
        result = self._run(side_effect=lambda plan: calls.append(1) or self._worker_result(plan),
                           verify=lambda *_a: (_ for _ in ()).throw(RuntimeError("checker unavailable")))

        self.assertEqual((result["status"], len(calls), len(result["attempts"])), ("error", 1, 1))
        self.assertIn("RuntimeError: checker unavailable", result["verification"]["reason"])

    def test_normal_failures_stop_for_xhigh_approval(self):
        efforts = []

        def worker(_task, selected_plan, **_kwargs):
            efforts.append(selected_plan.requested_effort)
            return self._worker_result(selected_plan)

        result = self._run(verify=lambda *_a: {"status": "failed", "exit_code": 1, "output_tail": "AssertionError"},
                           side_effect=lambda plan: worker(None, plan))

        self.assertEqual(efforts, ["low", "medium", "high"])
        self.assertEqual((result["status"], result["first_pass"], result["escalation_count"]),
                         ("approval_required", False, 2))
        self.assertEqual((result["next_effort"], result["approval_required"]), ("xhigh", True))
        self.assertIn("AssertionError", result["continuation_context"])

    def test_xhigh_runs_only_after_explicit_approval(self):
        efforts = []

        def worker(_task, selected_plan, **_kwargs):
            efforts.append(selected_plan.requested_effort)
            return self._worker_result(selected_plan)

        result = self._run(verify=lambda *_a: {"status": "failed", "exit_code": 1}, approve_xhigh=True,
                           side_effect=lambda plan: worker(None, plan))

        self.assertEqual(efforts, ["low", "medium", "high", "xhigh"])
        self.assertEqual((result["status"], result["escalation_count"], result["next_effort"]),
                         ("approval_required", 3, "max"))

    def test_xhigh_continuation_runs_only_xhigh(self):
        efforts = []

        def worker(_task, selected_plan, **_kwargs):
            efforts.append(selected_plan.requested_effort)
            return self._worker_result(selected_plan)

        result = self._run(approve_xhigh=True, start_effort="xhigh",
                           side_effect=lambda plan: worker(None, plan))

        self.assertEqual(efforts, ["xhigh"])
        self.assertEqual((result["status"], result["escalation_count"]), ("complete", 0))

    def test_rejects_unapproved_xhigh_continuation(self):
        with self.assertRaisesRegex(ValueError, "xhigh"):
            self._run(start_effort="xhigh")

    def test_rejects_non_execution_role_before_calling_worker(self):
        with self.assertRaisesRegex(ValueError, "execution"):
            self._run(plan=self._plan("review"))


class LowFirstCliTests(unittest.TestCase):
    @staticmethod
    def _result(plan):
        return {"message": "done", "model": plan.model, "requested_effort": plan.requested_effort,
                "applied_effort": plan.applied_effort, "usage": None, "status": "complete"}

    def test_low_first_requires_a_verifier(self):
        self.assertEqual(cli.main(["run", "--low-first", "--role", "fix", "--effort", "low", "task"],
                                  env={}, out=io.StringIO()), 2)

    def test_xhigh_requires_explicit_approval_for_one_shot_run(self):
        self.assertEqual(cli.main(["run", "--role", "fix", "--effort", "xhigh", "task"],
                                  env={}, out=io.StringIO()), 1)

    def test_default_run_uses_one_worker(self):
        with tempfile.TemporaryDirectory() as cwd, \
             patch.object(cli, "run_worker", side_effect=lambda _task, plan, **_kw: self._result(plan)) as worker, \
             patch.object(cli, "route_log"):
            status = cli.main(["run", "--role", "fix", "--effort", "low", "--cwd", cwd, "task"],
                              env={"HOME": cwd}, out=io.StringIO())
        self.assertEqual((status, worker.call_count), (0, 1))

    def test_low_first_wires_verifier_retry_and_log_fields(self):
        events = []
        captured = {}
        with tempfile.TemporaryDirectory() as cwd, \
             patch.object(cli, "run_low_first", side_effect=lambda task, plan, **kw: captured.update(task=task, plan=plan, **kw) or self._result(plan)) as loop, \
             patch.object(cli.route_log, "append", side_effect=lambda _d, _s, event: events.append(event)), \
             patch("model_effort_router.gate.run.run_check", return_value={"status": "passed", "exit_code": 0}) as check:
            status = cli.main(["run", "--low-first", "--retry-low", "--verify", "python -m unittest",
                               "--role", "fix", "--effort", "low", "--cwd", cwd, "task"],
                              env={"HOME": cwd}, out=io.StringIO())
        self.assertEqual((status, loop.call_count, captured["retry_low"]), (0, 1, True))
        captured["verify"](cwd, 12)
        self.assertEqual(check.call_count, 1)
        self.assertEqual(events[0]["policy"], "low-retry")

    def test_approved_xhigh_low_first_starts_from_xhigh(self):
        captured = {}
        with tempfile.TemporaryDirectory() as cwd, \
             patch.object(cli, "run_low_first", side_effect=lambda task, plan, **kw: captured.update(task=task, plan=plan, **kw) or self._result(plan)) as loop, \
             patch.object(cli.route_log, "append"):
            status = cli.main(["run", "--low-first", "--approve-xhigh", "--verify", "python -m unittest",
                               "--role", "fix", "--effort", "xhigh", "--cwd", cwd, "task"],
                              env={"HOME": cwd}, out=io.StringIO())
        self.assertEqual((status, loop.call_count, captured["approve_xhigh"], captured["start_effort"]),
                         (0, 1, True, "xhigh"))


if __name__ == "__main__":
    unittest.main()

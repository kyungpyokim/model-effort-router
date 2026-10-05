import contextlib
import io
import unittest
from evaluation import live_runner

class RetiredEvaluationSafetyTest(unittest.TestCase):
    def test_old_workflow_runner_refuses_to_dispatch(self):
        out=io.StringIO()
        with contextlib.redirect_stderr(out):
            self.assertEqual(live_runner.main(["--live"]),2)
        self.assertIn("automatic plan/gate/escalation/review protocol was removed",out.getvalue())

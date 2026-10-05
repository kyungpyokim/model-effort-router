import io
import unittest
from model_effort_router.cli import main

class AntigravityRoutingTest(unittest.TestCase):
    def test_route_is_allowed_but_worker_run_is_rejected_before_dispatch(self):
        out=io.StringIO()
        env={"HOME":"/nonexistent"}
        self.assertEqual(main(["route","--host","antigravity","--role","analysis","--effort","high","--json","analyze code"],env=env,out=out),0)
        self.assertEqual(main(["run","--host","antigravity","--role","analysis","--effort","high","analyze code"],env=env,out=io.StringIO()),2)
    def test_no_legacy_chat_or_level_flags(self):
        self.assertEqual(main(["chat","old"],env={},out=io.StringIO()),2)

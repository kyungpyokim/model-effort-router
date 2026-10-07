import json
import unittest

from model_effort_router.difficulty.decision import DifficultyInput
from model_effort_router.difficulty.openai_decisions import OpenAIDecisionsBackend

ANSWERS = {"answers": [{"name": "role", "type": "choice", "choice": "fix"},
                       {"name": "effort", "type": "choice", "choice": "low"}]}


class OpenAIDecisionsContextTest(unittest.TestCase):
    def sent(self, task):
        seen = {}

        def transport(url, headers, body, timeout):
            seen.update(json.loads(body))
            return 200, json.dumps(ANSWERS)
        OpenAIDecisionsBackend(transport=transport, env={"OPENAI_API_KEY": "k"}).classify(task, 3)
        return seen["input"]

    def test_session_context_precedes_the_task_only_when_present(self):
        with_ctx = self.sent(DifficultyInput("진행", ("a.py",), context="Session summary:\nplan X"))
        self.assertEqual(with_ctx, "Session context:\nSession summary:\nplan X\n\nCurrent request:\n진행\n\nRelevant paths:\na.py")
        self.assertEqual(self.sent(DifficultyInput("진행")), "Task:\n진행\n\nRelevant paths:\n(none)")


if __name__ == "__main__":
    unittest.main()

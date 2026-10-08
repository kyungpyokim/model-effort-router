import unittest
from evaluation import compare
from model_effort_router.difficulty.decision import DifficultyDecision


class Fake:
    name = "fake"

    def __init__(self, role, effort):
        self.role, self.effort = role, effort

    def classify(self, task, timeout_s):
        return DifficultyDecision(self.role, self.effort, self.name)


class RoleEffortEvaluationTest(unittest.TestCase):
    ROWS = [
        {
            "id": "a",
            "task": "Implement parser",
            "status": "adjudicated",
            "final": {"role": "implementation", "effort": "high"},
        },
        {"id": "b", "task": "Review diff", "status": "adjudicated", "final": {"role": "review", "effort": "medium"}},
        {"id": "old", "task": "old level case", "status": "adjudicated", "final": {"level": "L4"}},
    ]

    def test_scores_only_explicit_role_effort_labels(self):
        item = compare.evaluate_backend("fake", Fake("implementation", "high"), self.ROWS)
        self.assertEqual((item["n"], item["role_exact"], item["effort_exact"], item["joint_exact"]), (2, 1, 1, 1))
        self.assertEqual(item["predictions"][0], {"id": "a", "role": "implementation", "effort": "high"})

    def test_failed_classification_is_recorded_without_default_role(self):
        class Broken:
            name = "broken"

            def classify(self, *args):
                raise RuntimeError("offline")

        item = compare.evaluate_backend("broken", Broken(), self.ROWS)
        self.assertEqual((item["joint_exact"], item["fallback_count"], len(item["errors"])), (0, 2, 2))

    def test_report_disclaims_historical_level_corpora(self):
        report = compare.compare(self.ROWS, {"fake": Fake("review", "medium")})
        self.assertEqual(report["metric"], "role_effort")
        self.assertIn("Historical L1-L5 corpora are excluded", compare.to_markdown(report))

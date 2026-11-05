import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from evaluation import compare
from model_effort_router.difficulty.decision import DifficultyDecision


class Fake:
    name = "fake"

    def __init__(self, role, effort, tier=None):
        self.role, self.effort, self.tier = role, effort, tier

    def classify(self, task, timeout_s):
        return DifficultyDecision(self.role, self.effort, self.name, tier=self.tier)


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
        self.assertEqual(item["predictions"][0], {"id": "a", "role": "implementation", "effort": "high", "tier": None})

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


class TierEvaluationTest(unittest.TestCase):
    ROWS = [
        {
            "id": "a",
            "task": "t1",
            "status": "adjudicated",
            "final": {"role": "fix", "effort": "low", "tier": "economy"},
        },
        {
            "id": "b",
            "task": "t2",
            "status": "adjudicated",
            "final": {"role": "fix", "effort": "low", "tier": "frontier"},
        },
        {"id": "c", "task": "t3", "status": "adjudicated", "final": {"role": "fix", "effort": "low"}},
    ]

    def test_tier_scored_only_on_tier_labeled_rows(self):
        item = compare.evaluate_backend("fake", Fake("fix", "low", "economy"), self.ROWS)
        self.assertEqual((item["n"], item["tier_n"], item["tier_exact"], item["joint_exact"]), (3, 2, 1, 3))
        self.assertEqual(item["predictions"][0]["tier"], "economy")

    def test_none_tier_is_a_miss_not_an_error(self):
        item = compare.evaluate_backend("fake", Fake("fix", "low"), self.ROWS)
        self.assertEqual((item["tier_n"], item["tier_exact"], item["errors"]), (2, 0, []))

    def test_markdown_tier_column(self):
        md = compare.to_markdown(compare.compare(self.ROWS, {"fake": Fake("fix", "low", "economy")}))
        self.assertIn("Tier exact", md)
        self.assertIn("1/2 (50%)", md)
        plain = compare.to_markdown(compare.compare(self.ROWS[2:], {"fake": Fake("fix", "low")}))
        self.assertIn("| - |", plain)


class CliTest(unittest.TestCase):
    def test_cli_with_fake_backend_prints_table_and_writes_json(self):
        with tempfile.TemporaryDirectory() as d:
            corpus = Path(d) / "c.jsonl"
            row = {
                "id": "a",
                "task": "Fix bug",
                "status": "adjudicated",
                "labels": [
                    {"labeler": "x", "role": "fix", "effort": "low", "tier": "economy"},
                    {"labeler": "y", "role": "fix", "effort": "low", "tier": "economy"},
                ],
                "final": {"role": "fix", "effort": "low", "tier": "economy"},
            }
            corpus.write_text(json.dumps(row) + "\n")
            out_json = Path(d) / "out.json"
            seen = []

            def factory(name, user_config):
                seen.append(name)
                return Fake("fix", "low", "economy")

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = compare.main(
                    [str(corpus), "--backend", "one", "--backend", "two", "--json", str(out_json), "--timeout", "5"],
                    backend_factory=factory,
                )
            self.assertEqual((code, seen), (0, ["one", "two"]))
            self.assertIn("| one | 1 |", buf.getvalue())
            data = json.loads(out_json.read_text())
            self.assertEqual(set(data["backends"]), {"one", "two"})
            self.assertEqual(data["backends"]["one"]["tier_exact"], 1)

    def test_cli_requires_backend_and_reports_bad_corpus(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            compare.main(["x.jsonl"])
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(
                compare.main(["/nonexistent.jsonl", "--backend", "jev"], backend_factory=lambda *a: None), 1
            )

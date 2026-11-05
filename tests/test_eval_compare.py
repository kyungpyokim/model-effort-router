import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        self.assertNotIn("Tier exact", plain)


class Isolated(unittest.TestCase):
    """Run in a temp cwd with MER_USER_CONFIG pointing at a temp file (never the developer's real config)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)
        self.user_cfg = self.d / "user.json"
        patcher = patch.dict(os.environ, {"MER_USER_CONFIG": str(self.user_cfg)})
        patcher.start()
        self.addCleanup(patcher.stop)
        old = os.getcwd()
        os.chdir(self.d)
        self.addCleanup(os.chdir, old)

    def corpus(self, tier=True):
        final = {"role": "fix", "effort": "low", **({"tier": "economy"} if tier else {})}
        row = {
            "id": "a",
            "task": "Fix bug",
            "status": "adjudicated",
            "labels": [
                {"labeler": "x", "role": "fix", "effort": "low"},
                {"labeler": "y", "role": "fix", "effort": "low"},
            ],
            "final": final,
        }
        path = self.d / "c.jsonl"
        path.write_text(json.dumps(row) + "\n")
        return str(path)

    def run_main(self, argv, factory=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = compare.main(argv, backend_factory=factory)
        return code, out.getvalue(), err.getvalue()


class BuildBackendTest(unittest.TestCase):
    def build(self, name, repo=None, user=None):
        captured = {}

        def fake_create(n, registry=None, **options):
            captured.update(name=n, **options)
            return object()

        with patch("model_effort_router.difficulty.registry.create", fake_create):
            compare.build_backend(name, repo, user)
        return captured

    def test_jev_key_and_model_from_user_config(self):
        got = self.build("jev", user={"jev": {"api_key": "k", "model": "m"}})
        self.assertEqual(got, {"name": "jev", "api_key": "k", "model": "m"})

    def test_jev_without_config_passes_nothing(self):
        self.assertEqual(self.build("jev"), {"name": "jev"})
        self.assertEqual(self.build("jev", user={}), {"name": "jev"})

    def test_openai_key(self):
        got = self.build("openai_decisions", user={"openai": {"api_key": "ok"}})
        self.assertEqual(got, {"name": "openai_decisions", "api_key": "ok"})

    def test_nimble_options_from_repo_config(self):
        repo = {"difficulty": {"backend": "nimble", "nimble": {"model": "tiny"}}}
        got = self.build("nimble", repo=repo)
        self.assertEqual(got["options"]["model"], "tiny")
        self.assertNotIn("options", self.build("nimble"))

    def test_unknown_backend_lists_valid_names(self):
        with self.assertRaises(ValueError) as cm:
            compare.build_backend("nope")
        self.assertIn("'nope'", str(cm.exception))
        self.assertIn("jev", str(cm.exception))


class MarkdownTierColumnTest(unittest.TestCase):
    def test_tierless_output_matches_legacy_format(self):
        rows = [{"id": "a", "task": "t", "status": "adjudicated", "final": {"role": "fix", "effort": "low"}}]
        md = compare.to_markdown(compare.compare(rows, {"fake": Fake("fix", "low")}))
        self.assertEqual(
            md,
            "# Role / effort comparison (1 adjudicated cases)\n\n"
            "Historical L1-L5 corpora are excluded; this report scores only explicit role and effort labels.\n\n"
            "| Provider | Cases | Role exact | Effort exact | Joint exact | Provider failures |\n"
            "|---|---:|---:|---:|---:|---:|\n"
            "| fake | 1 | 1/1 (100%) | 1/1 (100%) | 1/1 (100%) | 0 |\n",
        )

    def test_tier_column_only_when_some_backend_has_tier_rows(self):
        rows = [
            {
                "id": "a",
                "task": "t",
                "status": "adjudicated",
                "final": {"role": "fix", "effort": "low", "tier": "economy"},
            }
        ]
        md = compare.to_markdown(compare.compare(rows, {"fake": Fake("fix", "low", "economy")}))
        self.assertIn("# Role / effort / tier comparison", md)
        self.assertIn("| Joint exact | Tier exact | Provider failures |", md)
        self.assertIn("| 1/1 (100%) | 0 |", md)


class CliTest(Isolated):
    def test_cli_with_fake_backend_prints_table_and_writes_json(self):
        out_json = self.d / "out.json"
        seen = []

        def factory(name, repo, user):
            seen.append((name, repo, user))
            return Fake("fix", "low", "economy")

        code, out, _ = self.run_main(
            [self.corpus(), "--backend", "one", "--backend", "two", "--json", str(out_json), "--timeout", "5"], factory
        )
        self.assertEqual((code, [x[0] for x in seen]), (0, ["one", "two"]))
        self.assertEqual(seen[0][1:], (None, None))
        self.assertIn("| one | 1 |", out)
        data = json.loads(out_json.read_text())
        self.assertEqual(set(data["backends"]), {"one", "two"})
        self.assertEqual(data["backends"]["one"]["tier_exact"], 1)

    def test_user_config_is_passed_to_factory(self):
        self.user_cfg.write_text(json.dumps({"jev": {"api_key": "secret"}}))
        seen = []
        self.run_main(
            [self.corpus(), "--backend", "x"], lambda n, r, u: seen.append(u) or Fake("fix", "low", "economy")
        )
        self.assertEqual(seen, [{"jev": {"api_key": "secret"}}])

    def test_non_dict_user_config_is_clean_error(self):
        self.user_cfg.write_text("[1]")
        code, _, err = self.run_main([self.corpus(), "--backend", "jev"], lambda *a: Fake("fix", "low"))
        self.assertEqual(code, 1)
        self.assertIn("compare: user config must be", err)

    def test_unknown_backend_is_clean_error(self):
        code, _, err = self.run_main([self.corpus(), "--backend", "nope"])
        self.assertEqual(code, 1)
        self.assertIn("compare: unknown backend 'nope'", err)

    def test_bad_json_path_fails_before_any_classification(self):
        calls = []

        class Counting(Fake):
            def classify(self, task, timeout_s):
                calls.append(1)
                return super().classify(task, timeout_s)

        code, _, err = self.run_main(
            [self.corpus(), "--backend", "x", "--json", str(self.d / "missing" / "o.json")],
            lambda *a: Counting("fix", "low"),
        )
        self.assertEqual((code, calls), (1, []))
        self.assertIn("compare:", err)

    def test_all_cases_failing_warns_and_exits_nonzero(self):
        class Broken:
            name = "broken"

            def classify(self, *args):
                raise RuntimeError("no key")

        code, out, err = self.run_main([self.corpus(), "--backend", "broken"], lambda *a: Broken())
        self.assertEqual(code, 1)
        self.assertIn("'broken'", err)
        self.assertIn("ClassificationError", err)
        self.assertIn("| broken |", out)

    def test_cli_requires_backend_and_reports_bad_corpus(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            compare.main(["x.jsonl"])
        code, _, err = self.run_main(["/nonexistent.jsonl", "--backend", "jev"], lambda *a: None)
        self.assertEqual(code, 1)
        self.assertIn("compare:", err)

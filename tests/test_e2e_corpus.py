from __future__ import annotations

import json
import re
import sys
import unittest
from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import e2e_corpus  # noqa: E402

CORPUS_DIR = ROOT / "evals" / "execution_corpus"
MANIFEST_PATH = CORPUS_DIR / "cases.json"
CASES_MD_PATH = CORPUS_DIR / "CASES.md"
ALLOWED_TASK_TYPES = {"implementation", "local_refactoring", "architectural_refactoring"}
EXPECTED_LEVEL_COUNTS = Counter({"L1": 3, "L2": 3, "L3": 3, "L4": 3, "L5": 3})
FREEZE_REVISION = "v1"
FREEZE_DATE = "2026-09-26"


def case_ids_in_cases_md() -> list[str]:
    """Case IDs from the frozen-order table in CASES.md, in document order."""
    ids: list[str] = []
    for line in CASES_MD_PATH.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\|\s*\d+\s*\|\s*([A-Za-z0-9_]+)\s*\|", line)
        if match:
            ids.append(match.group(1))
    return ids


class ExecutionCorpusManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases: Sequence[e2e_corpus.ExecutionCase] = e2e_corpus.load_execution_cases(MANIFEST_PATH)

    def test_manifest_has_exactly_15_unique_cases(self):
        names = [case.name for case in self.cases]

        self.assertEqual(len(self.cases), 15)
        self.assertEqual(len(set(names)), 15, f"duplicate case IDs: {names}")

    def test_level_distribution_is_three_per_level(self):
        self.assertEqual(Counter(case.level for case in self.cases), EXPECTED_LEVEL_COUNTS)

    def test_task_types_stay_in_the_approved_three_value_set(self):
        for case in self.cases:
            with self.subTest(case=case.name):
                self.assertIn(case.task_type, ALLOWED_TASK_TYPES)

    def test_at_least_one_l5_case_is_elevated_security_tier(self):
        self.assertTrue(
            any(case.level == "L5" and case.tier == "elevated" for case in self.cases),
            "Execution Corpus v1 requires an elevated/security L5 case",
        )

    def test_fixture_dirs_are_relative_and_under_execution_corpus_fixtures(self):
        for case in self.cases:
            with self.subTest(case=case.name):
                self.assertTrue(case.fixture_dir.is_relative_to("evals/execution_corpus/fixtures")
                                and not case.fixture_dir.is_absolute(),
                                f"{case.fixture_dir} must be relative under evals/execution_corpus/fixtures")

    def test_every_test_cmd_is_non_empty(self):
        for case in self.cases:
            with self.subTest(case=case.name):
                self.assertTrue(case.test_cmd.strip(), "test_cmd must be non-empty")

    def test_every_case_has_a_non_empty_acceptance_description(self):
        for case in self.cases:
            with self.subTest(case=case.name):
                self.assertTrue(case.acceptance.strip(), "acceptance must be non-empty")

    def test_validate_execution_corpus_accepts_the_frozen_manifest(self):
        e2e_corpus.validate_execution_corpus(self.cases, ROOT)

    def test_cases_md_lists_the_same_ids_in_the_frozen_order(self):
        self.assertEqual(case_ids_in_cases_md(), [case.name for case in self.cases])

    def test_cases_md_records_the_freeze_revision_and_date(self):
        text = CASES_MD_PATH.read_text(encoding="utf-8")
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

        self.assertEqual(manifest["revision"], FREEZE_REVISION)
        self.assertEqual(manifest["freeze_date"], FREEZE_DATE)
        self.assertIn(f"`{FREEZE_REVISION}`", text)
        self.assertIn(FREEZE_DATE, text)

    def test_every_fixture_directory_exists(self):
        missing = [case.name for case in self.cases if not (ROOT / case.fixture_dir).is_dir()]

        self.assertEqual(
            missing,
            [],
            "missing fixture directories (fixtures must be committed): "
            + ", ".join(missing),
        )

    def test_cases_md_records_the_fixture_freeze_boundary(self):
        text = CASES_MD_PATH.read_text(encoding="utf-8")

        self.assertIn("Fixture freeze", text)
        self.assertIn("test: complete frozen e2e execution fixtures", text)
        self.assertIn(
            "unless a documented corpus revision triggers paired reruns", text
        )


class ValidateExecutionCorpusTests(unittest.TestCase):
    def setUp(self):
        self.cases = e2e_corpus.load_execution_cases(MANIFEST_PATH)

    def test_rejects_a_wrong_level_distribution(self):
        mutated = (replace(self.cases[0], level="L2"),) + self.cases[1:]

        with self.assertRaises(ValueError):
            e2e_corpus.validate_execution_corpus(mutated, ROOT)

    def test_rejects_a_manifest_with_the_wrong_case_count(self):
        with self.assertRaises(ValueError):
            e2e_corpus.validate_execution_corpus(self.cases[:-1], ROOT)

    def test_rejects_a_disallowed_task_type(self):
        mutated = (replace(self.cases[0], task_type="design"),) + self.cases[1:]

        with self.assertRaises(ValueError):
            e2e_corpus.validate_execution_corpus(mutated, ROOT)

    def test_rejects_a_fixture_dir_outside_the_fixture_root(self):
        mutated = (replace(self.cases[0], fixture_dir=Path("evals/execution_corpus/other/x")),) + self.cases[1:]

        with self.assertRaises(ValueError):
            e2e_corpus.validate_execution_corpus(mutated, ROOT)

    def test_requires_an_elevated_l5_case(self):
        mutated = tuple(
            replace(case, tier="standard") if case.level == "L5" else case
            for case in self.cases
        )

        with self.assertRaises(ValueError):
            e2e_corpus.validate_execution_corpus(mutated, ROOT)

    def test_rejects_blank_test_cmd_and_acceptance(self):
        for field in ("test_cmd", "acceptance"):
            with self.subTest(field=field):
                mutated = (replace(self.cases[0], **{field: " "}),) + self.cases[1:]

                with self.assertRaises(ValueError):
                    e2e_corpus.validate_execution_corpus(mutated, ROOT)


if __name__ == "__main__":
    unittest.main()

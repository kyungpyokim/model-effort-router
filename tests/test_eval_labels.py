import csv
import json
import tempfile
import unittest
from pathlib import Path

from evaluation import cases, labels

CORPUS = [
    {"id": "a", "task": "Fix typo", "paths": ["README.md"], "status": "draft"},
    {"id": "b", "task": "What is this?", "status": "draft"},
]


class LabelsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)
        self.corpus = self.d / "c.jsonl"
        self.corpus.write_text("".join(json.dumps(c) + "\n" for c in CORPUS))

    def test_sheet_has_role_effort_fields_and_merge_makes_labeled(self):
        sheet = self.d / "kim.tsv"
        labels.write_sheet(str(self.corpus), str(sheet))
        with sheet.open() as stream:
            rows = list(csv.DictReader(stream, delimiter="\t"))
        self.assertEqual(tuple(rows[0]), labels.TSV_FIELDS)
        rows[0].update(labeler="kim", role="fix", effort="low")
        rows[1].update(labeler="kim", role="analysis", effort="low")
        with sheet.open("w", newline="") as f:
            w = csv.DictWriter(f, labels.TSV_FIELDS, delimiter="\t")
            w.writeheader()
            w.writerows(rows)
        other = self.d / "claude.jsonl"
        other.write_text(
            json.dumps({"id": "a", "labeler": "claude", "role": "fix", "effort": "medium"})
            + "\n"
            + json.dumps({"id": "b", "labeler": "claude", "role": "analysis", "effort": "low"})
            + "\n"
        )
        out = labels.merge(str(self.corpus), [str(sheet), str(other)])
        self.assertEqual([r["status"] for r in out], ["labeled", "labeled"])
        self.assertEqual(cases.agreement(out)["effort_mismatches"], ["a"])

    def test_unknown_id_and_bad_label_are_rejected(self):
        bad = self.d / "x.jsonl"
        bad.write_text(json.dumps({"id": "zz", "labeler": "k", "role": "fix", "effort": "low"}) + "\n")
        with self.assertRaises(cases.CorpusError):
            labels.merge(str(self.corpus), [str(bad)])
        bad.write_text(
            json.dumps({"id": "a", "labeler": "k", "role": "fix", "effort": "extreme"})
            + "\n"
            + json.dumps({"id": "a", "labeler": "j", "role": "fix", "effort": "low"})
            + "\n"
        )
        with self.assertRaises(cases.CorpusError):
            labels.merge(str(self.corpus), [str(bad)])


if __name__ == "__main__":
    unittest.main()


class TierLabelsTest(unittest.TestCase):
    setUp = LabelsTest.setUp

    def test_sheet_tier_column_roundtrip_and_empty_cell_means_no_tier(self):
        sheet = self.d / "kim.tsv"
        labels.write_sheet(str(self.corpus), str(sheet), tier=True)
        with sheet.open() as stream:
            rows = list(csv.DictReader(stream, delimiter="\t"))
        self.assertEqual(tuple(rows[0]), labels.TSV_FIELDS_TIER)
        self.assertEqual(labels.TSV_FIELDS_TIER.index("tier"), labels.TSV_FIELDS_TIER.index("effort") + 1)
        rows[0].update(labeler="kim", role="fix", effort="low", tier="economy")
        rows[1].update(labeler="kim", role="analysis", effort="low", tier="")
        with sheet.open("w", newline="") as f:
            w = csv.DictWriter(f, labels.TSV_FIELDS_TIER, delimiter="\t")
            w.writeheader()
            w.writerows(rows)
        read = labels.read_labels(str(sheet))
        self.assertEqual(read[0]["tier"], "economy")
        self.assertNotIn("tier", read[1])

    def test_old_sheet_has_no_tier_column(self):
        sheet = self.d / "old.tsv"
        labels.write_sheet(str(self.corpus), str(sheet))
        self.assertNotIn("tier", sheet.read_text().splitlines()[0])

    def test_unknown_header_rejected(self):
        sheet = self.d / "bad.tsv"
        sheet.write_text("id\ttier\n")
        with self.assertRaises(cases.CorpusError):
            labels.read_labels(str(sheet))

    def test_merge_with_and_without_tier(self):
        a = self.d / "a.jsonl"
        a.write_text(
            json.dumps({"id": "a", "labeler": "x", "role": "fix", "effort": "low", "tier": "economy"})
            + "\n"
            + json.dumps({"id": "b", "labeler": "x", "role": "fix", "effort": "low"})
            + "\n"
        )
        b = self.d / "b.jsonl"
        b.write_text(
            json.dumps({"id": "a", "labeler": "y", "role": "fix", "effort": "low", "tier": "frontier"})
            + "\n"
            + json.dumps({"id": "b", "labeler": "y", "role": "fix", "effort": "low"})
            + "\n"
        )
        out = labels.merge(str(self.corpus), [str(a), str(b)])
        self.assertEqual(out[0]["labels"][0]["tier"], "economy")
        self.assertNotIn("tier", out[1]["labels"][0])
        rep = cases.agreement(out)
        self.assertEqual((rep["tier_compared"], rep["tier_mismatches"]), (1, ["a"]))

    def test_merge_rejects_bad_tier_and_extra_keys(self):
        bad = self.d / "bad.jsonl"
        bad.write_text(json.dumps({"id": "a", "labeler": "x", "role": "fix", "effort": "low", "tier": "huge"}) + "\n")
        with self.assertRaises(cases.CorpusError):
            labels.merge(str(self.corpus), [str(bad)])
        extra = self.d / "extra.jsonl"
        extra.write_text(json.dumps({"id": "a", "labeler": "x", "role": "fix", "effort": "low", "foo": 1}) + "\n")
        with self.assertRaises(cases.CorpusError):
            labels.merge(str(self.corpus), [str(extra)])

    def test_cli_sheet_tier_flag(self):
        sheet = self.d / "cli.tsv"
        self.assertEqual(labels.main(["sheet", "--tier", str(self.corpus), str(sheet)]), 0)
        self.assertIn("tier", sheet.read_text().splitlines()[0].split("\t"))

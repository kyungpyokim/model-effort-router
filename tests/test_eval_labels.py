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

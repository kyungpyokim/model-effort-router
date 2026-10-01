import csv
import json
import tempfile
import unittest
from pathlib import Path

from evaluation import cases, labels

CORPUS = [{"id": "a", "task": "Fix typo", "paths": ["README.md"], "status": "draft",
           "proposed": {"level": "L1", "risk_flags": [], "target": "route"}},
          {"id": "b", "task": "What is this?", "status": "draft"}]


class LabelsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)
        self.corpus = self.d / "c.jsonl"
        self.corpus.write_text("".join(json.dumps(c) + "\n" for c in CORPUS))

    def test_sheet_hides_proposed_and_merge_of_two_labelers_makes_labeled(self):
        sheet = self.d / "kim.tsv"
        labels.write_sheet(str(self.corpus), str(sheet))
        text = sheet.read_text()
        self.assertNotIn("proposed", text)
        self.assertNotIn("L1", text)  # the author's suggestion never reaches the labeler
        rows = list(csv.DictReader(sheet.open(), delimiter="\t"))
        rows[0].update(labeler="kim", level="L1", target="route")
        rows[1].update(labeler="kim", level="", target="no_route")
        with sheet.open("w", newline="") as f:
            w = csv.DictWriter(f, labels.TSV_FIELDS, delimiter="\t")
            w.writeheader()
            w.writerows(rows)
        other = self.d / "claude.jsonl"
        other.write_text(json.dumps({"id": "a", "labeler": "claude", "level": "L2", "risk_flags": [], "target": "route"}) + "\n"
                         + json.dumps({"id": "b", "labeler": "claude", "level": None, "risk_flags": [], "target": "no_route"}) + "\n")
        out = labels.merge(str(self.corpus), [str(sheet), str(other)])
        self.assertEqual([r["status"] for r in out], ["labeled", "labeled"])
        self.assertNotIn("proposed", out[0])
        self.assertEqual(cases.agreement(out)["discuss"], ["a"])

    def test_unknown_id_and_bad_label_are_rejected(self):
        bad = self.d / "x.jsonl"
        bad.write_text(json.dumps({"id": "zz", "labeler": "k", "level": "L1", "risk_flags": [], "target": "route"}) + "\n")
        with self.assertRaises(cases.CorpusError):
            labels.merge(str(self.corpus), [str(bad)])
        bad.write_text(json.dumps({"id": "a", "labeler": "k", "level": "L9", "risk_flags": [], "target": "route"}) + "\n"
                       + json.dumps({"id": "a", "labeler": "j", "level": "L1", "risk_flags": [], "target": "route"}) + "\n")
        with self.assertRaises(cases.CorpusError):
            labels.merge(str(self.corpus), [str(bad)])


if __name__ == "__main__":
    unittest.main()

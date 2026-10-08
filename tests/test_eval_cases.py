import json
import tempfile
import unittest
from pathlib import Path

from evaluation import cases

ROOT = Path(__file__).resolve().parent.parent


def label(who, role="fix", effort="medium"):
    return {"labeler": who, "role": role, "effort": effort}


def case(id="c1", **over):
    base = {"id": id, "task": "Fix the bug in parser.py", "status": "draft"}
    base.update(over)
    return base


def adjudicated(id="c1", a="fix", b="fix", final="fix", effort="medium", **over):
    return case(
        id, status="adjudicated", labels=[label("a", a), label("b", b)], final={"role": final, "effort": effort}, **over
    )


def write(rows):
    f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    f.write("\n".join(r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) for r in rows))
    f.close()
    return f.name


class ValidateTest(unittest.TestCase):
    def bad(self, row, needle):
        with self.assertRaises(cases.CorpusError) as cm:
            cases.validate_case(row)
        self.assertIn(needle, str(cm.exception))

    def test_minimal_draft_ok_and_normalized(self):
        out = cases.validate_case(case())
        self.assertEqual((out["paths"], out["labels"]), ([], []))

    def test_required_and_types(self):
        self.bad(case(id=""), "id")
        self.bad(case(task="  "), "task")
        self.bad(case(paths="a.py"), "paths")
        self.bad(case(status="weird"), "status")
        self.bad(case(surprise=1), "unknown field")
        self.bad("nope", "object")

    def test_draft_has_no_labels_or_final(self):
        self.bad(case(labels=[label("a")]), "draft")
        self.bad(case(final={"role": "fix", "effort": "low"}), "final")

    def test_legacy_proposals_are_rejected(self):
        self.bad(case(proposed={"role": "review", "effort": "high"}), "unknown field")

    def test_label_fields(self):
        self.bad(case(status="labeled", labels=[label("a", role="invent"), label("b")]), "role")
        self.bad(case(status="labeled", labels=[label("a", effort="extreme"), label("b")]), "effort")
        self.bad(case(status="labeled", labels=[{**label("a"), "level": "L2"}, label("b")]), "unknown field")
        self.bad(case(status="labeled", labels=[label(""), label("b")]), "labeler")

    def test_labeled_needs_two_distinct_labelers(self):
        self.bad(case(status="labeled", labels=[label("a")]), "2")
        self.bad(case(status="labeled", labels=[label("a"), label("a")]), "distinct")

    def test_adjudicated_needs_final_and_labeled_must_not_have_it(self):
        self.bad(case(status="adjudicated", labels=[label("a"), label("b")]), "final")
        self.bad(
            case(status="labeled", labels=[label("a"), label("b")], final={"role": "fix", "effort": "low"}), "final"
        )


class LoadTest(unittest.TestCase):
    def test_load_reports_line_number_and_bad_json(self):
        path = write([case("a"), "{not json"])
        with self.assertRaises(cases.CorpusError) as cm:
            cases.load(path)
        self.assertIn("line 2", str(cm.exception))

    def test_duplicate_ids_rejected_with_line(self):
        with self.assertRaises(cases.CorpusError) as cm:
            cases.load(write([case("a"), case("a")]))
        self.assertIn("duplicate", str(cm.exception))
        self.assertIn("line 2", str(cm.exception))

    def test_blank_lines_ignored_and_unicode_kept(self):
        rows = cases.load(write([case("a", task="로그인 버그 수정 🚀"), "", case("b")]))
        self.assertEqual([r["id"] for r in rows], ["a", "b"])
        self.assertIn("🚀", rows[0]["task"])

    def test_adjudicated_filter(self):
        rows = cases.load(write([case("a"), adjudicated("b")]))
        self.assertEqual([r["id"] for r in cases.adjudicated(rows)], ["b"])


class AgreementTest(unittest.TestCase):
    def test_reports_exact_agreement_and_mismatches_by_dimension(self):
        rows = [
            case("same", status="labeled", labels=[label("a"), label("b")]),
            case("role", status="labeled", labels=[label("a", "fix"), label("b", "implementation")]),
            case("effort", status="labeled", labels=[label("a", effort="low"), label("b", effort="high")]),
            case("both", status="labeled", labels=[label("a", "fix", "low"), label("b", "review", "high")]),
            case("draft"),
        ]
        rep = cases.agreement(rows)
        self.assertEqual(rep["compared"], 4)
        self.assertEqual((rep["role_exact"], rep["effort_exact"], rep["joint_exact"]), (2, 2, 1))
        self.assertEqual(rep["role_mismatches"], ["role", "both"])
        self.assertEqual(rep["effort_mismatches"], ["effort", "both"])

    def test_empty(self):
        self.assertEqual(cases.agreement([])["compared"], 0)


class SeedTest(unittest.TestCase):
    def setUp(self):
        self.rows = cases.load(ROOT / "evaluation" / "corpus" / "role-effort-seed.jsonl")

    def test_seed_is_unlabeled_draft_only(self):
        self.assertGreaterEqual(len(self.rows), 40)
        for r in self.rows:
            self.assertEqual((r["status"], r["labels"]), ("draft", []), r["id"])
            self.assertEqual(set(r), {"id", "task", "paths", "status", "labels"})
            self.assertNotIn("proposed", r)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path

from evaluation import cases

ROOT = Path(__file__).resolve().parent.parent


def label(who, level="L2", flags=(), target="route"):
    return {"labeler": who, "level": level, "risk_flags": list(flags), "target": target}


def case(id="c1", **over):
    base = {"id": id, "task": "Fix the bug in parser.py", "status": "draft"}
    base.update(over)
    return base


def adjudicated(id="c1", a="L2", b="L2", final="L2", **over):
    return case(id, status="adjudicated", labels=[label("a", a), label("b", b)],
                final={"level": final, "risk_flags": [], "target": "route"}, **over)


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
        self.bad(case(final={"level": "L1", "risk_flags": [], "target": "route"}), "final")

    def test_proposed_is_validated(self):
        cases.validate_case(case(proposed={"level": "L3", "risk_flags": ["auth"], "target": "route"}))
        self.bad(case(proposed={"level": "L9", "risk_flags": [], "target": "route"}), "level")

    def test_label_fields(self):
        self.bad(case(status="labeled", labels=[label("a", level="L9"), label("b")]), "level")
        self.bad(case(status="labeled", labels=[label("a", flags=["nope"]), label("b")]), "risk flag")
        self.bad(case(status="labeled", labels=[label("a", target="x"), label("b")]), "target")
        self.bad(case(status="labeled", labels=[label(""), label("b")]), "labeler")

    def test_no_route_requires_null_level_and_route_requires_level(self):
        cases.validate_case(case(status="labeled", labels=[label("a", None, target="no_route"),
                                                           label("b", None, target="no_route")]))
        self.bad(case(status="labeled", labels=[label("a", "L1", target="no_route"), label("b")]), "no_route")
        self.bad(case(status="labeled", labels=[label("a", None), label("b")]), "level")

    def test_labeled_needs_two_distinct_labelers(self):
        self.bad(case(status="labeled", labels=[label("a")]), "2")
        self.bad(case(status="labeled", labels=[label("a"), label("a")]), "distinct")

    def test_adjudicated_needs_final_and_labeled_must_not_have_it(self):
        self.bad(case(status="adjudicated", labels=[label("a"), label("b")]), "final")
        self.bad(case(status="labeled", labels=[label("a"), label("b")],
                      final={"level": "L1", "risk_flags": [], "target": "route"}), "final")


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
    def test_buckets_by_level_distance(self):
        rows = [
            case("same", status="labeled", labels=[label("a", "L2"), label("b", "L2")]),
            case("one", status="labeled", labels=[label("a", "L2"), label("b", "L3")]),
            case("two", status="labeled", labels=[label("a", "L1"), label("b", "L3")]),
            case("three", status="labeled", labels=[label("a", "L1"), label("b", "L2"), label("c", "L4")]),
            case("draft"),
        ]
        rep = cases.agreement(rows)
        self.assertEqual(rep["compared"], 4)
        self.assertEqual(rep["exact_agree"], 1)
        self.assertEqual(rep["discuss"], ["one"])
        self.assertEqual(rep["revise_guide"], ["two", "three"])

    def test_risk_flag_or_target_disagreement_needs_discussion(self):
        rows = [case("flags", status="labeled", labels=[label("a", "L3", ["auth"]), label("b", "L3")]),
                case("target", status="labeled", labels=[label("a", "L3"), label("b", "L3", target="plan_only")]),
                case("nr", status="labeled", labels=[label("a", None, target="no_route"), label("b", "L1")])]
        rep = cases.agreement(rows)
        self.assertEqual(rep["discuss"], ["flags", "target", "nr"])
        self.assertEqual(rep["revise_guide"], [])

    def test_empty(self):
        self.assertEqual(cases.agreement([])["compared"], 0)


class SeedTest(unittest.TestCase):
    def setUp(self):
        self.rows = cases.load(ROOT / "evaluation" / "corpus" / "seed.jsonl")

    def test_seed_is_draft_only_with_proposals_and_no_labels(self):
        self.assertGreaterEqual(len(self.rows), 40)
        for r in self.rows:
            self.assertEqual((r["status"], r["labels"]), ("draft", []), r["id"])
            self.assertIn("proposed", r)
            self.assertNotIn("final", r)

    def test_seed_spans_levels_flags_and_targets(self):
        prop = [r["proposed"] for r in self.rows]
        self.assertEqual({p["level"] for p in prop if p["level"]}, {"L1", "L2", "L3", "L4", "L5"})
        self.assertEqual({f for p in prop for f in p["risk_flags"]},
                         {"security", "auth", "payment", "data_migration", "data_loss", "concurrency"})
        self.assertEqual({p["target"] for p in prop}, {"route", "plan_only", "review_only", "no_route"})
        self.assertTrue([r for r in self.rows if r.get("note", "").startswith("ambiguous")])


if __name__ == "__main__":
    unittest.main()



class PilotStatusTest(unittest.TestCase):
    ROW = {"id": "p1", "task": "t", "status": "pilot",
           "labels": [{"labeler": "author", "level": "L2", "risk_flags": [], "target": "route"}],
           "final": {"level": "L2", "risk_flags": [], "target": "route"}}

    def _load(self, row):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "c.jsonl"
            path.write_text(json.dumps(row) + "\n")
            return cases.load(str(path))

    def test_pilot_allows_single_labeler_and_is_runnable_not_scored(self):
        rows = self._load(self.ROW)
        self.assertEqual([r["id"] for r in cases.runnable(rows)], ["p1"])
        self.assertEqual(cases.adjudicated(rows), [])

    def test_pilot_requires_final(self):
        with self.assertRaises(cases.CorpusError):
            self._load({k: v for k, v in self.ROW.items() if k != "final"})

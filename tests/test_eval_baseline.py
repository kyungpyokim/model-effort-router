import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from evaluation import baseline


def rec(case="c1", mode="baseline", total=1000, gate="passed", review=None, fix=0, req=True, wall=60.0):
    return {
        "case_id": case,
        "mode": mode,
        "gate_overall": gate,
        "review_verdict": review,
        "fix_rounds": fix,
        "requirements_met": req,
        "wall_s": wall,
        "usage": {
            "orchestrator": {"input": total, "cached_input": 0, "output": 0, "reasoning_output": 0},
            "classifier": None,
            "stages": {},
            "total": total,
            "subagent_rollouts": 0,
            "stages_without_usage": [],
        },
    }


def router(case="c1", active=True, children=2, missing=(), findings=1, **kw):
    kw.setdefault("review", "approved")
    r = rec(case, "router", **kw)
    r.update(router_active=active, review_findings=findings)
    r["usage"].update(subagent_rollouts=children, stages_without_usage=list(missing))
    return r


class ValidateRecordTest(unittest.TestCase):
    def bad(self, row, needle):
        with self.assertRaises(ValueError) as cm:
            baseline.validate_record(row)
        self.assertIn(needle, str(cm.exception))

    def test_ok(self):
        self.assertEqual(baseline.validate_record(rec())["mode"], "baseline")

    def test_rejects_bad_fields(self):
        self.bad(rec(mode="other"), "mode")
        self.bad(rec(case=""), "case_id")
        self.bad(rec(gate="meh"), "gate_overall")
        self.bad(rec(review="lgtm"), "review_verdict")
        self.bad(rec(fix=-1), "fix_rounds")
        self.bad(rec(req="yes"), "requirements_met")
        self.bad(rec(wall=-1), "wall_s")
        self.bad({**rec(), "usage": {"total": "x"}}, "usage")
        self.bad({**rec(), "router_active": "yes"}, "router_active")
        self.bad({**rec(), "review_findings": -1}, "review_findings")

    def test_unknown_review_verdict_is_valid_and_counts_as_not_approved(self):
        self.assertEqual(baseline.validate_record(router(review="unknown"))["review_verdict"], "unknown")
        self.assertEqual(
            baseline.compare_pair(rec(review="approved"), router(review="unknown"))["quality"], "regressed"
        )

    def test_run_defaults_to_one_and_must_be_a_positive_int(self):
        self.assertEqual(baseline.validate_record(rec())["run"], 1)
        self.assertEqual(baseline.validate_record({**rec(), "run": 3})["run"], 3)
        self.bad({**rec(), "run": 0}, "run")
        self.bad({**rec(), "run": "1"}, "run")

    def test_requirements_met_may_be_unset(self):
        self.assertIsNone(baseline.validate_record(rec(req=None))["requirements_met"])


class ComparePairTest(unittest.TestCase):
    def test_quality_preserved_with_deltas(self):
        c = baseline.compare_pair(rec(total=1000, wall=60, fix=0), router(total=700, wall=90, fix=1, review="approved"))
        self.assertEqual(c["quality"], "preserved")
        self.assertEqual((c["usage_delta"], c["time_delta_s"], c["fix_delta"]), (-300, 30, 1))
        self.assertAlmostEqual(c["usage_delta_pct"], -30.0)

    def test_regressed_when_a_shared_signal_gets_worse(self):
        self.assertEqual(baseline.compare_pair(rec(), router(gate="failed"))["quality"], "regressed")
        self.assertEqual(baseline.compare_pair(rec(), router(req=False))["quality"], "regressed")

    def test_improved_when_better_and_nothing_worse(self):
        self.assertEqual(baseline.compare_pair(rec(gate="failed"), router(gate="passed"))["quality"], "improved")

    def test_signals_missing_on_one_side_are_not_compared(self):
        # baseline has no review verdict, so the router's changes_requested cannot count as regression
        self.assertEqual(baseline.compare_pair(rec(), router(review="changes_requested"))["quality"], "preserved")

    def test_unknown_when_no_shared_signal(self):
        self.assertEqual(
            baseline.compare_pair(rec(gate=None, req=None), router(gate=None, req=None))["quality"], "unknown"
        )


class ReportTest(unittest.TestCase):
    def test_auto_allowed_when_quality_kept_and_usage_cut(self):
        rep = baseline.report(
            [rec("a", total=1000), router("a", total=800), rec("b", total=500), router("b", total=400)]
        )
        self.assertEqual(rep["decision"]["verdict"], "auto_allowed")
        self.assertEqual(rep["aggregate"]["usage"], {"baseline": 1500, "router": 1200, "delta": -300})
        self.assertEqual(rep["aggregate"]["quality"], {"preserved": 2, "improved": 0, "regressed": 0, "unknown": 0})

    def test_not_auto_when_usage_not_reduced(self):
        rep = baseline.report([rec("a", total=1000), router("a", total=1000)])
        self.assertEqual(rep["decision"]["verdict"], "do_not_default_to_auto")

    def test_not_auto_when_any_case_regressed_even_if_cheaper(self):
        rep = baseline.report([rec("a", total=1000), router("a", total=100, gate="failed")])
        self.assertEqual(rep["decision"]["verdict"], "do_not_default_to_auto")

    def test_insufficient_without_manual_requirements_flag_or_pairs(self):
        self.assertEqual(
            baseline.report([rec("a", req=None), router("a", total=1)])["decision"]["verdict"], "insufficient_data"
        )
        self.assertEqual(baseline.report([])["decision"]["verdict"], "insufficient_data")
        self.assertEqual(baseline.report([rec("a")])["aggregate"]["unpaired"], ["a"])

    def test_inactive_router_pair_is_excluded_so_it_cannot_pass_as_a_second_baseline(self):
        rep = baseline.report(
            [rec("a", total=1000), router("a", total=1, active=False), rec("b", total=1000), router("b", total=800)]
        )
        self.assertEqual(rep["aggregate"]["pairs"], 1)
        self.assertEqual(rep["aggregate"]["excluded"], [{"case_id": "a", "reason": "router_inactive"}])
        self.assertEqual(rep["decision"]["verdict"], "insufficient_data")
        self.assertEqual(rep["aggregate"]["usage"], {"baseline": 1000, "router": 800, "delta": -200})

    def test_errored_router_run_is_incomplete_not_excluded_as_inactive(self):
        e = router("a", total=1, active=False)
        e["error"] = "TimeoutError: slow"
        rep = baseline.report([rec("a"), e])
        self.assertEqual(rep["aggregate"]["excluded"], [])
        self.assertEqual(rep["aggregate"]["pairs"], 1)
        self.assertIn("run_error", rep["decision"]["reason"])
        self.assertEqual(rep["decision"]["verdict"], "insufficient_data")

    def test_never_auto_allowed_when_anything_was_excluded(self):
        rep = baseline.report(
            [rec("a", total=1000), router("a", total=100), rec("b", total=1000), router("b", total=1, active=False)]
        )
        self.assertEqual(rep["decision"]["verdict"], "insufficient_data")
        self.assertIn("router_inactive", rep["decision"]["reason"])

    def test_excluded_does_not_hide_a_real_regression(self):
        rep = baseline.report(
            [rec("a", total=1000), router("a", total=100, gate="failed"), rec("b"), router("b", active=False)]
        )
        self.assertEqual(rep["decision"]["verdict"], "do_not_default_to_auto")

    def test_insufficient_when_every_router_run_inactive(self):
        rep = baseline.report([rec("a"), router("a", total=1, active=False)])
        self.assertEqual(rep["decision"]["verdict"], "insufficient_data")

    def test_router_record_without_router_active_flag_is_not_trusted(self):
        r = router("a", total=1)
        del r["router_active"]
        self.assertEqual(baseline.report([rec("a"), r])["decision"]["verdict"], "insufficient_data")

    def test_contaminated_baseline_excluded(self):
        b = rec("a")
        b["contaminated"] = True
        rep = baseline.report([b, router("a", total=1)])
        self.assertEqual(rep["aggregate"]["excluded"], [{"case_id": "a", "reason": "baseline_contaminated"}])
        self.assertEqual(rep["decision"]["verdict"], "insufficient_data")

    def test_insufficient_when_stage_usage_missing_or_nothing_measured_for_router(self):
        for bad in (router("a", total=1, missing=["review"]), router("a", total=0)):
            self.assertEqual(baseline.report([rec("a"), bad])["decision"]["verdict"], "insufficient_data")

    def test_insufficient_on_error_or_incomplete_reasons(self):
        r = router("a", total=1)
        r["usage"]["incomplete_reasons"] = ["classifier_usage_missing"]
        self.assertEqual(baseline.report([rec("a"), r])["decision"]["verdict"], "insufficient_data")
        e = router("a", total=1)
        e["error"] = "TimeoutError: slow"
        self.assertEqual(baseline.report([rec("a"), e])["decision"]["verdict"], "insufficient_data")

    def test_review_findings_reported(self):
        rep = baseline.report([rec("a"), router("a", total=1, findings=3)])
        self.assertEqual(rep["aggregate"]["review_findings"], 3)
        self.assertEqual(rep["per_case"][0]["router_findings"], 3)
        self.assertIn("findings", baseline.to_markdown(rep).lower())

    def test_duplicate_mode_for_case_is_an_error(self):
        with self.assertRaises(ValueError):
            baseline.report([rec("a"), rec("a")])

    def test_markdown_has_decision_and_per_case_rows(self):
        md = baseline.to_markdown(baseline.report([rec("a"), router("a", total=900)]))
        self.assertIn("auto_allowed", md)
        self.assertIn("| a |", md)


class RepeatTest(unittest.TestCase):
    def runs(self):
        return [
            {**rec("a", total=1000), "run": 1},
            {**router("a", total=900), "run": 1},
            {**rec("a", total=2000), "run": 2},
            {**router("a", total=1000), "run": 2},
            rec("b", total=500),
            router("b", total=400),
        ]  # no run field = run 1

    def test_pairs_by_case_and_run_with_per_case_means_and_totals(self):
        rep = baseline.report(self.runs())
        self.assertEqual([(p["case_id"], p["run"]) for p in rep["per_case"]], [("a", 1), ("a", 2), ("b", 1)])
        self.assertEqual(rep["aggregate"]["usage"], {"baseline": 3500, "router": 2300, "delta": -1200})
        a = rep["per_case_mean"][0]
        self.assertEqual(
            (a["case_id"], a["runs"], a["baseline_mean"], a["router_mean"], a["usage_delta_mean"]),
            ("a", 2, 1500, 950, -550),
        )
        self.assertIn("Per-case means", baseline.to_markdown(rep))

    def test_run_two_without_partner_is_unpaired_and_exclusions_name_the_run(self):
        rep = baseline.report(
            [
                rec("a"),
                router("a"),
                {**rec("a"), "run": 2},
                {**router("a", active=False), "run": 3},
                {**rec("a"), "run": 3},
            ]
        )
        self.assertEqual(rep["aggregate"]["unpaired"], ["a#r2"])
        self.assertEqual(rep["aggregate"]["excluded"], [{"case_id": "a", "run": 3, "reason": "router_inactive"}])

    def test_same_mode_twice_in_one_run_is_a_duplicate(self):
        with self.assertRaises(ValueError):
            baseline.report([rec("a"), rec("a")])
        baseline.report([rec("a"), {**rec("a"), "run": 2}])


class MarkRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "runs.jsonl"
        rows = [{**rec("a", req=None), "run": k} for k in (1, 2)] + [rec("a", "router", req=None)]
        self.path.write_text("\n".join(json.dumps(r) for r in rows))

    def cli(self, *argv):
        self.err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(self.err):
            return baseline.main(list(argv))

    def test_run_required_when_several_runs_of_that_mode(self):
        self.assertEqual(self.cli("mark", str(self.path), "a", "baseline", "yes"), 1)
        self.assertIn("--run", self.err.getvalue())
        self.assertEqual(self.cli("mark", str(self.path), "a", "router", "yes"), 0)  # single run: not needed

    def test_mark_with_run_touches_only_that_run(self):
        self.assertEqual(self.cli("mark", str(self.path), "a", "baseline", "no", "--run", "2"), 0)
        got = {
            (r["mode"], r.get("run", 1)): r["requirements_met"]
            for r in map(json.loads, self.path.read_text().splitlines())
        }
        self.assertEqual(got, {("baseline", 1): None, ("baseline", 2): False, ("router", 1): None})
        self.assertEqual(self.cli("mark", str(self.path), "a", "baseline", "no", "--run", "9"), 1)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "runs.jsonl"
        self.path.write_text("\n".join(json.dumps(r) for r in [rec("a", req=None), router("a", total=800, req=None)]))

    def cli(self, *argv):
        out = io.StringIO()
        self.err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(self.err):
            return baseline.main(list(argv)), out.getvalue()

    def test_mark_sets_requirements_then_report_decides(self):
        self.assertEqual(self.cli("mark", str(self.path), "a", "baseline", "yes")[0], 0)
        self.assertEqual(self.cli("mark", str(self.path), "a", "router", "yes")[0], 0)
        jp = Path(self.tmp.name) / "r.json"
        rc, out = self.cli("report", str(self.path), "--json", str(jp))
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(jp.read_text())["decision"]["verdict"], "auto_allowed")

    def test_mark_rejects_duplicates_with_clear_error(self):
        with self.path.open("a") as f:
            f.write("\n" + json.dumps(rec("a", req=None)))
        self.assertEqual(self.cli("mark", str(self.path), "a", "baseline", "yes")[0], 1)
        self.assertIn("duplicate", self.err.getvalue())

    def test_mark_unknown_run_fails(self):
        self.assertEqual(self.cli("mark", str(self.path), "zzz", "router", "no")[0], 1)


if __name__ == "__main__":
    unittest.main()

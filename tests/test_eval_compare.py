import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from evaluation import compare
from model_effort_router.difficulty.decision import DifficultyDecision


class Fake:
    """Answers from a {task: level} table; raises for unknown tasks. Optional per-call usage and fake clock."""

    def __init__(self, name, answers, flags=None, usage=None):
        self.name, self.answers, self.flags, self.usage = name, answers, flags or {}, usage
        self.last_usage = None

    def classify(self, task, timeout_s):
        if task.task not in self.answers:
            raise RuntimeError("boom")
        self.last_usage = self.usage
        return DifficultyDecision(self.answers[task.task], self.name,
                                  risk_flags=tuple(self.flags.get(task.task, ())))


def case(id, task, level, flags=(), target="route"):
    lab = lambda who: {"labeler": who, "level": level, "risk_flags": list(flags), "target": target}
    return {"id": id, "task": task, "paths": [], "status": "adjudicated", "labels": [lab("a"), lab("b")],
            "final": {"level": level, "risk_flags": list(flags), "target": target}}


class Clock:
    def __init__(self, steps):
        self.t, self.steps = 0.0, iter(steps)

    def __call__(self):
        self.t += next(self.steps, 0.0)
        return self.t


CASES = [case("c1", "Fix typo in a.py", "L1"), case("c2", "Fix bug in b.py", "L2"),
         case("c3", "Add feature across files in c.py", "L3"),
         case("c4", "Refactor module d.py architecture", "L4"),
         case("c5", "Fix the auth bug in e.py", "L3", ["auth"])]


class EvaluateBackendTest(unittest.TestCase):
    def run_fake(self, answers, **kw):
        return compare.evaluate_backend("fake", Fake("fake", answers, **kw), CASES, clock=Clock([0.0, 0.1] * 5))

    def test_exact_within_one_and_direction_counts(self):
        m = self.run_fake({"Fix typo in a.py": "L1", "Fix bug in b.py": "L3",
                           "Add feature across files in c.py": "L1",
                           "Refactor module d.py architecture": "L4", "Fix the auth bug in e.py": "L3"})
        self.assertEqual((m["n"], m["exact"], m["within_one"]), (5, 3, 4))
        self.assertEqual((m["over"], m["under"]), (1, 1))
        self.assertAlmostEqual(m["mean_distance"], (0 + 1 + 2 + 0 + 0) / 5)
        self.assertEqual(m["fallback_count"], 0)

    def test_critical_miss_counts_l4_l5_and_risk_flag_cases_predicted_l2_or_lower(self):
        m = self.run_fake({"Fix typo in a.py": "L1", "Fix bug in b.py": "L2",
                           "Add feature across files in c.py": "L3",
                           "Refactor module d.py architecture": "L2",  # L4 -> L2: miss
                           "Fix the auth bug in e.py": "L2"})  # flagged -> L2: miss
        self.assertEqual((m["critical_total"], m["critical_miss"]), (2, 2))

    def test_right_l2_on_a_risk_flagged_l2_case_is_not_a_critical_miss(self):
        c = case("r", "Add CSRF check to the form handler in f.py", "L2", ["security"])
        self.assertEqual(compare.evaluate_backend("f", Fake("f", {c["task"]: "L2"}), [c])["critical_miss"], 0)
        self.assertEqual(compare.evaluate_backend("f", Fake("f", {c["task"]: "L1"}), [c])["critical_miss"], 1)

    def test_l3_prediction_on_critical_is_not_a_critical_miss(self):
        m = self.run_fake({"Refactor module d.py architecture": "L3", "Fix the auth bug in e.py": "L3"})
        self.assertEqual(m["critical_miss"], 0)

    def test_failed_backend_counts_as_fallback_and_scored_as_default_l3(self):
        m = self.run_fake({})
        self.assertEqual(m["fallback_count"], 5)
        self.assertEqual(m["exact"], 2)  # default L3 equals the two L3 cases

    def test_latency_p50_and_max_in_ms(self):
        clock = Clock([0.0, 0.1, 0.0, 0.3, 0.0, 0.2, 0.0, 0.05, 0.0, 0.4])
        b = Fake("fake", {c["task"]: "L3" for c in CASES})
        m = compare.evaluate_backend("fake", b, CASES, clock=clock)
        self.assertAlmostEqual(m["latency_ms"]["p50"], 200, places=3)
        self.assertAlmostEqual(m["latency_ms"]["max"], 400, places=3)

    def test_token_usage_summed_only_if_backend_reports_it(self):
        ans = {c["task"]: "L3" for c in CASES}
        with_usage = compare.evaluate_backend("f", Fake("f", ans, usage={"input_tokens": 10, "output_tokens": 2}), CASES)
        self.assertEqual(with_usage["tokens"], {"input": 50, "output": 10})
        self.assertIsNone(compare.evaluate_backend("f", Fake("f", ans), CASES)["tokens"])

    def test_usage_counted_even_when_call_failed_and_not_carried_between_calls(self):
        class Flaky(Fake):
            def classify(self, task, timeout_s):
                if task.task == "Fix bug in b.py":
                    self.last_usage = {"input_tokens": 4, "output_tokens": 1}
                    raise RuntimeError("bad output")
                return super().classify(task, timeout_s)

        ans = {c["task"]: "L3" for c in CASES}
        m = compare.evaluate_backend("f", Flaky("f", ans, usage=None), CASES)
        self.assertEqual(m["tokens"], {"input": 4, "output": 1})  # stale usage not re-counted on later calls
        self.assertEqual(m["fallback_count"], 1)

    def test_routing_level_stage_profile_match(self):
        ans = {c["task"]: c["final"]["level"] for c in CASES}
        perfect = compare.evaluate_backend("f", Fake("f", ans), CASES)
        self.assertEqual(perfect["stage_profile_match"], 5)
        # auth case predicted L3 without the flag: detector sees 'auth' in the task so profiles still match
        weak = dict(ans, **{"Fix bug in b.py": "L3"})  # L2 -> L3 changes profiles
        self.assertEqual(compare.evaluate_backend("f", Fake("f", weak), CASES)["stage_profile_match"], 4)

    def test_target_respected_when_comparing_profiles(self):
        c = case("p", "Write a plan only for the migration in db.py", "L4", target="plan_only")
        m = compare.evaluate_backend("f", Fake("f", {c["task"]: "L4"}), [c])
        self.assertEqual(m["stage_profile_match"], 1)

    def test_level_distribution_kept_only_for_the_backends_own_decision(self):
        class Dist(Fake):
            def classify(self, task, timeout_s):
                d = super().classify(task, timeout_s)
                return DifficultyDecision(d.level, d.backend, distribution={"L1": 0.7, "L2": 0.3})
        ans = {c["task"]: c["final"]["level"] for c in CASES[:1]}
        m = compare.evaluate_backend("f", Dist("f", ans), CASES[:2])
        self.assertEqual(m["predictions"][0]["distribution"], {"L1": 0.7, "L2": 0.3})
        self.assertNotIn("distribution", m["predictions"][1])  # failed call: the default decision

    def test_risk_flags_scored_for_backend_alone_and_merged_with_rules(self):
        ans = {c["task"]: c["final"]["level"] for c in CASES}
        # backend flags auth on c5 (right) and payment on c1 (wrong); rules detect auth from "auth" in c5's text
        m = compare.evaluate_backend("f", Fake("f", ans, flags={"Fix the auth bug in e.py": ["auth"],
                                                                "Fix typo in a.py": ["payment"]}), CASES)
        self.assertEqual(m["risk"]["backend"], {"tp": 1, "fp": 1, "fn": 0})
        self.assertEqual(m["risk"]["merged"], {"tp": 1, "fp": 1, "fn": 0})
        silent = compare.evaluate_backend("f", Fake("f", ans), CASES)
        self.assertEqual((silent["risk"]["backend"], silent["risk"]["merged"]),
                         ({"tp": 0, "fp": 0, "fn": 1}, {"tp": 1, "fp": 0, "fn": 0}))
        self.assertEqual(m["predictions"][0], {"id": "c1", "level": "L1", "risk_flags": ["payment"],
                                                "target": "route", "target_source": "rules"})
        self.assertEqual(compare.regex_risk(CASES), {"tp": 1, "fp": 0, "fn": 0})
        self.assertIn("risk merged (rec / prec)", compare.to_markdown(compare.compare(CASES, {"f": Fake("f", ans)})))

    def test_no_route_and_non_adjudicated_cases_skipped(self):
        nr = {"id": "n", "task": "what is x", "status": "adjudicated", "paths": [],
              "labels": [], "final": {"level": None, "risk_flags": [], "target": "no_route"}}
        draft = {"id": "d", "task": "t", "status": "draft", "paths": [], "labels": []}
        m = compare.evaluate_backend("f", Fake("f", {}), [nr, draft, CASES[0]])
        self.assertEqual(m["n"], 1)
        self.assertEqual(m["skipped_no_route"], 1)

    def test_empty_corpus_gives_zero_rates_not_a_crash(self):
        m = compare.evaluate_backend("f", Fake("f", {}), [])
        self.assertEqual((m["n"], m["exact"], m["latency_ms"]), (0, 0, None))

    def test_misses_listed(self):
        m = self.run_fake({"Fix typo in a.py": "L2"})
        self.assertIn({"id": "c1", "final": "L1", "predicted": "L2"}, m["misses"])


class TargetAccuracyTest(unittest.TestCase):
    def test_uses_cheap_target_rules(self):
        rows = [case("a", "Fix the bug in parser.py", "L2"),
                case("b", "Explain how parser.py works", "L2", target="route")]  # rules say no_route
        self.assertEqual(compare.target_accuracy(rows), {"n": 2, "correct": 1, "text_only_correct": 1})

    def test_text_only_differs_from_with_paths(self):
        c = case("a", "Update this", "L2")
        c["paths"] = ["src/parser.py"]  # the path supplies the code context the text lacks
        self.assertEqual(compare.target_accuracy([c]), {"n": 1, "correct": 1, "text_only_correct": 0})


class TargetFake(Fake):
    """Decides the target like Jev: {task: target}."""
    provides_target = True

    def __init__(self, name, answers, targets, **kw):
        super().__init__(name, answers, **kw)
        self.targets = targets

    def classify(self, task, timeout_s):
        d = super().classify(task, timeout_s)
        return DifficultyDecision(d.level, d.backend, target=self.targets[task.task])


class BackendTargetTest(unittest.TestCase):
    ROWS = [case("r", "Bump the base image in the Dockerfile to python 3.12", "L2"),
            case("n", "Why is the sky blue?", None, target="no_route"),
            case("p", "Write a plan only for the migration in db.py", "L4", target="plan_only")]

    def run_backend(self, targets, calls=None):
        answers = {r["task"]: "L2" for r in self.ROWS}
        b = TargetFake("t", answers, dict(zip(answers, targets)))
        return compare.evaluate_backend("t", b, self.ROWS)

    def test_every_adjudicated_case_is_classified_but_level_scored_only_where_it_exists(self):
        m = self.run_backend(["route", "no_route", "plan_only"])
        self.assertEqual((m["n"], m["target_n"], m["target_correct"], m["target_from_backend"]), (2, 3, 3, 3))
        self.assertEqual(len(m["predictions"]), 3)
        self.assertEqual(m["predictions"][1], {"id": "n", "level": "L2", "risk_flags": [], "target": "no_route",
                                               "target_source": "backend"})
        self.assertEqual(m["exact"] + m["over"] + m["under"], 2)  # the no_route case is not in the level stats

    def test_wrong_backend_targets_are_counted(self):
        self.assertEqual(self.run_backend(["no_route", "route", "route"])["target_correct"], 0)

    def test_backend_without_target_is_scored_with_the_rules(self):
        answers = {r["task"]: "L2" for r in self.ROWS}
        m = compare.evaluate_backend("f", Fake("f", answers), self.ROWS)
        self.assertEqual(m["target_from_backend"], 0)
        self.assertEqual(m["predictions"][0]["target_source"], "rules")
        self.assertEqual(m["predictions"][0]["target"], "no_route")  # Dockerfile: rules miss it
        self.assertEqual(m["target_correct"], 2)

    def test_fallback_to_default_decision_uses_rules_for_the_target(self):
        m = compare.evaluate_backend("f", Fake("f", {}), self.ROWS)
        self.assertEqual((m["fallback_count"], m["target_from_backend"]), (3, 0))

    def test_markdown_has_target_column_and_both_rule_accuracies(self):
        res = compare.compare(self.ROWS, {"t": TargetFake("t", {r["task"]: "L2" for r in self.ROWS},
                                                          dict(zip([r["task"] for r in self.ROWS], ["route", "no_route", "plan_only"])))})
        md = compare.to_markdown(res)
        self.assertIn("target (backend)", md)
        self.assertIn("3/3 (100%)", md)
        self.assertIn("text-only (what the hook sees)", md)


class ReportTest(unittest.TestCase):
    def test_report_json_and_markdown(self):
        res = compare.compare(CASES, {"fake": Fake("fake", {c["task"]: "L3" for c in CASES})})
        self.assertEqual(res["cases"], 5)
        md = compare.to_markdown(res)
        self.assertIn("| fake |", md)
        self.assertIn("critical", md.lower())
        json.dumps(res)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.corpus = Path(self.tmp.name) / "c.jsonl"
        self.corpus.write_text("\n".join(json.dumps(c) for c in CASES), encoding="utf-8")

    def cli(self, *argv, registry=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = compare.main(list(argv), registry=registry)
        return rc, out.getvalue()

    def test_subscription_backend_refused_without_live(self):
        rc, out = self.cli("--corpus", str(self.corpus), "--backends", "subscription")
        self.assertEqual(rc, 2)

    def test_dry_run_lists_plan_without_calling_backends(self):
        calls = []
        reg = {"fake": lambda: calls.append(1) or Fake("fake", {})}
        rc, out = self.cli("--corpus", str(self.corpus), "--backends", "fake", "--dry-run", registry=reg)
        self.assertEqual((rc, calls), (0, []))
        self.assertIn("5", out)

    def test_runs_non_live_backend_and_writes_reports(self):
        reg = {"fake": lambda: Fake("fake", {c["task"]: "L3" for c in CASES})}
        jp, mp = Path(self.tmp.name) / "r.json", Path(self.tmp.name) / "r.md"
        rc, _ = self.cli("--corpus", str(self.corpus), "--backends", "fake", "--json", str(jp), "--md", str(mp),
                         registry=reg)
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(jp.read_text())["backends"]["fake"]["n"], 5)
        self.assertIn("fake", mp.read_text())

    def test_unknown_backend_and_empty_adjudicated_set_are_errors(self):
        self.assertEqual(self.cli("--corpus", str(self.corpus), "--backends", "zzz", registry={})[0], 2)
        empty = Path(self.tmp.name) / "e.jsonl"
        empty.write_text("")
        self.assertEqual(self.cli("--corpus", str(empty), "--backends", "fake",
                                  registry={"fake": lambda: Fake("fake", {})})[0], 1)


if __name__ == "__main__":
    unittest.main()

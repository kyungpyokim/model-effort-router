import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from model_effort_router.difficulty import conditional, jev
from model_effort_router.difficulty.chain import classify_with_fallback
from model_effort_router.difficulty.conditional import NimbleJevBackend, select_reasons
from model_effort_router.difficulty.decision import DifficultyDecision, DifficultyInput
from model_effort_router.difficulty.jev import GUIDE_LEVEL_QUESTION, JevBackend
from model_effort_router.difficulty.nimble import NimbleBackend
from model_effort_router.difficulty.registry import BACKENDS
from model_effort_router.policy.config import resolve_config
from model_effort_router.policy.router import route
from tests.test_jev import FakeTransport, response

FAKE_KEY = "fake-key-value-123"
TASK = DifficultyInput("Fix the discount rounding in pricing.py")
SURE = {"L1": 0.1, "L2": 0.8, "L3": 0.1}


def dec(dist=SURE, target="route", flags=(), level="L2", backend="x", codes=()):
    return DifficultyDecision(level, backend, distribution=dist, target=target, risk_flags=flags, reason_codes=codes)


class Stage:
    """A fake stage backend: returns `result` or raises `error`; records calls, usage and the clock it advances."""

    def __init__(self, result=None, error=None, usage=None, scores=None, takes=0.0, clock=None):
        self.result, self.error, self.last_usage, self.last_risk_scores = result, error, usage, scores
        self.calls, self.takes, self.clock = [], takes, clock

    def classify(self, task, timeout_s):
        self.calls.append((task, timeout_s))
        if self.clock:
            self.clock.t += self.takes
        if self.error:
            raise self.error
        return self.result


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


class SelectionTest(unittest.TestCase):
    """select_reasons works on the decision's RAW distribution (duck-typed here so boundaries can be exact)."""

    def reasons(self, dist, target="route", flags=(), task=TASK):
        return select_reasons(SimpleNamespace(distribution=dist, target=target, risk_flags=flags), task)

    def test_uncertainty_thresholds_are_strict(self):
        self.assertEqual(self.reasons({"L2": 0.60, "L3": 0.25, "L1": 0.15}), ())  # top exactly 0.60: not uncertain
        self.assertEqual(self.reasons({"L2": 0.599, "L3": 0.401}), ("uncertain",))
        self.assertEqual(self.reasons({"L2": 0.75, "L3": 0.59}), ())  # margin 0.16
        self.assertEqual(self.reasons({"L2": 0.75, "L3": 0.61}), ("uncertain",))  # margin 0.14
        self.assertEqual(self.reasons({"L2": 0.75, "L3": 0.60}), ())  # margin 0.15 (float noise 0.1500000000000000x is not < 0.15)
        self.assertEqual((conditional.UNCERTAIN_TOP, conditional.UNCERTAIN_MARGIN), (0.60, 0.15))

    def test_missing_or_single_entry_distribution_is_uncertain(self):
        self.assertEqual(self.reasons(None), ("uncertain",))
        self.assertEqual(self.reasons({}), ("uncertain",))
        self.assertEqual(self.reasons({"L2": 1.0}), ("uncertain",))

    def test_scoped_targets(self):
        for target, expected in (("plan_only", ("scoped",)), ("review_only", ("scoped",)), ("route", ()), ("no_route", ()), (None, ())):
            self.assertEqual(self.reasons(SURE, target), expected, target)

    def test_risk_from_the_decision_or_from_the_rule_detector(self):
        self.assertEqual(self.reasons(SURE, flags=("auth",)), ("risk",))
        self.assertEqual(self.reasons(SURE, task=DifficultyInput("rename a variable in app.py", ("db/migrations/a.py",))), ("risk",))
        self.assertEqual(self.reasons(SURE, task=DifficultyInput("Fix the login check in app.py")), ("risk",))  # text alone
        self.assertEqual(self.reasons(SURE, task=DifficultyInput("rename a variable in app.py")), ())

    def test_reasons_come_in_a_fixed_order_and_combine(self):
        r = self.reasons({"L2": 0.5, "L3": 0.5}, "plan_only", ("auth",))
        self.assertEqual(r, ("uncertain", "scoped", "risk"))


def backend(nimble, jev_stage, clock=None):
    return NimbleJevBackend(nimble=nimble, jev=jev_stage, clock=clock or Clock())


class ChainTest(unittest.TestCase):
    def test_unselected_returns_nimble_and_never_calls_jev(self):
        n, j = Stage(dec(codes=("nimble", "m"))), Stage(dec(level="L4"))
        d = backend(n, j).classify(TASK, 12)
        self.assertEqual((d.level, d.backend, d.reason_codes), ("L2", "nimble_jev", ("nimble", "m", "nimble_jev:nimble")))
        self.assertEqual((n.calls, j.calls), ([(TASK, 10.0)], []))

    def test_selected_returns_jev_with_stage_and_why_codes(self):
        n = Stage(dec({"L2": 0.5, "L3": 0.5}, target="review_only"))
        j = Stage(dec(level="L3", backend="jev", codes=("jev", "jev-1")))
        d = backend(n, j).classify(TASK, 12)
        self.assertEqual((d.level, d.backend), ("L3", "nimble_jev"))
        self.assertEqual(d.reason_codes, ("jev", "jev-1", "nimble_jev:jev", "nimble_jev_why:uncertain", "nimble_jev_why:scoped"))
        self.assertEqual(len(j.calls), 1)

    def test_nimble_failure_goes_to_jev_with_its_reason(self):
        j = Stage(dec(level="L3", backend="jev"))
        d = backend(Stage(error=ConnectionRefusedError()), j).classify(TASK, 12)
        self.assertEqual((d.level, d.backend), ("L3", "nimble_jev"))
        self.assertIn("nimble_jev_why:nimble_failure", d.reason_codes)
        self.assertEqual(len(j.calls), 1)

    def test_jev_failure_raises_naming_both_and_never_returns_nimble(self):
        n = Stage(dec(flags=("auth",), codes=("nimble",)))
        with self.assertRaises(RuntimeError) as cm:
            backend(n, Stage(error=TimeoutError())).classify(TASK, 12)
        self.assertIn("jev failed (TimeoutError) after risk", str(cm.exception))
        with self.assertRaises(RuntimeError) as cm:
            backend(Stage(error=ValueError("bad")), Stage(error=TimeoutError())).classify(TASK, 12)
        self.assertIn("nimble failed (ValueError)", str(cm.exception))

    def test_the_fallback_chain_moves_on_after_a_jev_failure(self):
        chain = backend(Stage(dec(target="plan_only")), Stage(error=RuntimeError("down")))
        fallback = Stage(dec(level="L3", backend="subscription"))
        fallback.name = "subscription"
        chain_decision = classify_with_fallback(TASK, [chain, fallback], 12)
        self.assertEqual((chain_decision.level, chain_decision.backend), ("L3", "subscription"))
        self.assertIn("fallback_cause:nimble_jev:RuntimeError", chain_decision.reason_codes)
        self.assertEqual(len(fallback.calls), 1)

    def test_attributes(self):
        b = backend(Stage(dec()), Stage(dec()))
        self.assertEqual((b.name, b.calls_model, b.provides_target), ("nimble_jev", True, True))
        self.assertEqual(BACKENDS["nimble_jev"], NimbleJevBackend)

    def test_target_and_flags_of_the_returned_stage_are_kept(self):
        d = backend(Stage(dec(target="route")), Stage()).classify(TASK, 12)
        self.assertEqual(d.target, "route")
        j = Stage(dec(target="plan_only", flags=("auth",), backend="jev"))
        d = backend(Stage(dec(flags=("auth",))), j).classify(TASK, 12)
        self.assertEqual((d.target, d.risk_flags), ("plan_only", ("auth",)))


class UsageAndBudgetTest(unittest.TestCase):
    def test_usage_sums_both_stages_and_risk_scores_follow_the_returned_stage(self):
        n = Stage(dec(flags=("auth",)), usage={"input_tokens": 100, "output_tokens": 10}, scores={"auth": 0.9})
        j = Stage(dec(backend="jev"), usage={"input_tokens": 541, "output_tokens": 119}, scores={"auth": 0.7})
        b = backend(n, j)
        b.classify(TASK, 12)
        self.assertEqual((b.last_usage, b.last_risk_scores), ({"input_tokens": 641, "output_tokens": 129}, {"auth": 0.7}))

    def test_unselected_reports_nimble_usage_only_and_none_when_nothing_reported(self):
        b = backend(Stage(dec(), usage={"input_tokens": 100, "output_tokens": 10}, scores={"auth": 0.1}), Stage())
        b.classify(TASK, 12)
        self.assertEqual((b.last_usage, b.last_risk_scores), ({"input_tokens": 100, "output_tokens": 10}, {"auth": 0.1}))
        b = backend(Stage(dec()), Stage())
        b.classify(TASK, 12)
        self.assertIsNone(b.last_usage)

    def test_usage_survives_failures_and_resets_per_call(self):
        n = Stage(error=TimeoutError(), usage={"input_tokens": 5, "output_tokens": 0})
        j = Stage(error=RuntimeError("x"), usage={"input_tokens": 7, "output_tokens": 1})
        b = backend(n, j)
        with self.assertRaises(RuntimeError):
            b.classify(TASK, 12)
        self.assertEqual(b.last_usage, {"input_tokens": 12, "output_tokens": 1})  # billed even though unusable
        n.result, n.error, n.last_usage = dec(), None, None
        b.classify(TASK, 12)
        self.assertIsNone(b.last_usage)

    def test_nimble_is_capped_to_leave_jev_a_usable_budget(self):
        clock = Clock()
        n, j = Stage(dec(target="plan_only"), takes=4.0, clock=clock), Stage(dec(backend="jev"))
        backend(n, j, clock).classify(TASK, 12)
        self.assertEqual((n.calls[0][1], j.calls[0][1]), (10.0, 8.0))  # nimble 12 - 2; jev gets what is left of the 12 s
        self.assertEqual(conditional.JEV_RESERVE_S, 2.0)
        clock.t = 0.0
        n, j = Stage(dec(target="plan_only"), takes=11.5, clock=clock), Stage(dec(backend="jev"))
        backend(n, j, clock).classify(TASK, 12)
        self.assertEqual(j.calls[0][1], 1.0)  # the existing floor
        clock.t = 0.0
        n, j = Stage(error=TimeoutError(), takes=10.0, clock=clock), Stage(dec(backend="jev"))
        backend(n, j, clock).classify(TASK, 12)
        self.assertEqual(j.calls[0][1], 2.0)  # a capped Nimble timeout still leaves Jev its 2 s
        for tiny, expected in ((2.5, 1.0), (1.0, 1.0)):  # never below 1 s for the Nimble stage either
            n = Stage(dec())
            backend(n, Stage()).classify(TASK, tiny)
            self.assertEqual(n.calls[0][1], 1.0 if tiny - 2.0 < 1.0 else tiny - 2.0, tiny)


class RequestTest(unittest.TestCase):
    def test_the_guide_question_is_sent_by_both_default_stages(self):
        b = NimbleJevBackend(env={jev.KEY_ENV: FAKE_KEY})
        tn, tj = FakeTransport(response(target="plan_only")), FakeTransport(response())
        b._nimble._transport, b._jev._transport = tn, tj
        d = b.classify(TASK, 12)  # plan_only is scoped -> Jev
        for t in (tn, tj):
            self.assertEqual(t.calls[0][2]["questions"]["level"], GUIDE_LEVEL_QUESTION)
            self.assertEqual({k: v for k, v in t.calls[0][2]["questions"].items() if k != "level"},
                             {k: v for k, v in jev.QUESTIONS.items() if k != "level"})
        self.assertNotIn("Authorization", tn.calls[0][1])  # the local stage sends no credential
        self.assertEqual(tj.calls[0][1]["Authorization"], f"Bearer {FAKE_KEY}")
        self.assertTrue(tn.calls[0][0].startswith("http://127.0.0.1"))
        self.assertEqual(d.backend, "nimble_jev")

    def test_guide_question_is_the_recorded_object(self):
        recorded = Path(__file__).resolve().parent.parent / "runs" / "live-guide-level-question-20261004.json"
        if recorded.exists():  # runs/ is gitignored evaluation output: compared only where present
            self.assertEqual(GUIDE_LEVEL_QUESTION, json.loads(recorded.read_text()))
        self.assertEqual(GUIDE_LEVEL_QUESTION["type"], "score")
        self.assertEqual([c[:2] for c in GUIDE_LEVEL_QUESTION["criteria"]], ["L1", "L2", "L3", "L4", "L5"])
        self.assertNotEqual(GUIDE_LEVEL_QUESTION, jev.QUESTIONS["level"])

    def test_plain_backends_are_unchanged_by_default(self):
        tn, tj = FakeTransport(response()), FakeTransport(response())
        NimbleBackend(tn, env={}).classify(TASK, 5)
        JevBackend(tj, env={jev.KEY_ENV: FAKE_KEY}).classify(TASK, 5)
        for t in (tn, tj):
            self.assertEqual(t.calls[0][2]["questions"], jev.QUESTIONS)
        t = FakeTransport(response())
        JevBackend(t, env={jev.KEY_ENV: FAKE_KEY}, level_question=GUIDE_LEVEL_QUESTION).classify(TASK, 5)
        self.assertEqual(t.calls[0][2]["questions"], {**jev.QUESTIONS, "level": GUIDE_LEVEL_QUESTION})

    def test_end_to_end_unselected_never_touches_the_jev_transport(self):
        b = NimbleJevBackend(env={})  # no TYPESAFE_API_KEY: an accidental Jev call would raise
        b._nimble._transport = FakeTransport(response((0, 0.9, 0.1, 0, 0), confidence=0.8))
        b._jev._transport = FakeTransport(response())
        d = b.classify(TASK, 12)
        self.assertEqual((d.level, b._jev._transport.calls), ("L2", []))
        self.assertIn("nimble_jev:nimble", d.reason_codes)


class OptionsPlumbingTest(unittest.TestCase):
    CFG = {"difficulty": {"backend": "nimble_jev", "nimble": {"model": "nimble:2b", "l4_promote_prob": 0.3}}}

    def test_config_accepts_the_backend_name_and_keeps_nimble_options(self):
        cfg = resolve_config(repo=self.CFG, registry=BACKENDS)
        self.assertEqual((cfg.backend, cfg.nimble), ("nimble_jev", {"model": "nimble:2b", "l4_promote_prob": 0.3}))
        with self.assertRaises(ValueError):
            resolve_config(repo={"difficulty": {"backend": "nimble_jevv"}}, registry=BACKENDS)

    def test_router_passes_nimble_options_only_to_the_real_class(self):
        seen = []

        def classify(self, task, timeout_s):
            seen.append(self._nimble._options)
            return dec(backend="nimble_jev")

        with mock.patch.object(NimbleJevBackend, "classify", classify):
            route("Fix the discount bug in pricing.py", repo_config=self.CFG, registry={"nimble_jev": NimbleJevBackend})
        self.assertEqual(seen, [{"model": "nimble:2b", "l4_promote_prob": 0.3}])
        made = []
        reg = {"nimble_jev": lambda **kw: made.append(kw) or backend(Stage(dec()), Stage())}
        route("Fix the discount bug in pricing.py", repo_config=self.CFG, registry=reg)
        self.assertEqual(made, [{}])  # a double gets no options

    def test_router_routes_through_the_chain_and_logs_summed_usage(self):
        n = Stage(dec(target="route"), usage={"input_tokens": 100, "output_tokens": 10})
        plan = route("Fix the discount bug in pricing.py", repo_config={"difficulty": {"backend": "nimble_jev"}},
                     registry={"nimble_jev": lambda **kw: backend(n, Stage())})
        self.assertEqual((plan.decision.backend, plan.target, plan.target_source), ("nimble_jev", "route", "backend"))
        self.assertEqual((plan.classifier_usage["input_tokens"], plan.classifier_usage["output_tokens"]), (100, 10))

    def test_compare_passes_nimble_options_to_nimble_jev_and_gates_it_behind_live(self):
        from evaluation import compare
        self.assertIn("nimble_jev", compare.LIVE_BACKENDS)
        seen = []

        def factory(**kw):
            seen.append(kw)
            return type("Stub", (), {"name": "nimble_jev", "classify": lambda self, t, s: dec(backend="nimble_jev")})()

        case = {"id": "c", "task": TASK.task, "paths": [], "status": "adjudicated",
                "labels": [{"labeler": w, "level": "L2", "risk_flags": [], "target": "route"} for w in ("a", "b")],
                "final": {"level": "L2", "risk_flags": [], "target": "route"}}
        with tempfile.TemporaryDirectory() as d:
            corpus = Path(d) / "c.jsonl"
            corpus.write_text(json.dumps(case))
            old = os.getcwd()
            try:
                os.chdir(d)
                argv = ["--corpus", str(corpus), "--backends", "nimble_jev"]
                with mock.patch.dict(os.environ, {"HOME": d, "MER_USER_CONFIG": str(Path(d) / "none.json")}):
                    with contextlib.redirect_stderr(io.StringIO()):
                        self.assertEqual(compare.main(argv, registry={"nimble_jev": factory}), 2)  # no --live
                    with mock.patch.object(compare, "NimbleJevBackend", factory), contextlib.redirect_stdout(io.StringIO()):
                        compare.main(argv + ["--live"], registry={"nimble_jev": factory})
                        (Path(d) / ".model-effort-router.json").write_text(json.dumps({"difficulty": {"nimble": {"model": "nimble:2b"}}}))
                        compare.main(argv + ["--live"], registry={"nimble_jev": factory})
            finally:
                os.chdir(old)
        self.assertEqual(seen, [{}, {"options": {"model": "nimble:2b"}}])


if __name__ == "__main__":
    unittest.main()

import json
import unittest
from pathlib import Path
from unittest import mock

from model_effort_router.difficulty.decision import RISK_FLAGS, DifficultyDecision, DifficultyInput
from model_effort_router.difficulty import jev
from model_effort_router.difficulty.jev import KEY_ENV, MODEL_ENV, URL, JevBackend
from model_effort_router.difficulty.registry import BACKENDS
from model_effort_router.difficulty.subscription import MAX_PATHS, MAX_TASK_CHARS, SubscriptionBackend
from model_effort_router.policy.router import route
from tests.test_mer_cli import CliCase

FAKE_CRED = "fake-cred-value-123"
ENV = {KEY_ENV: FAKE_CRED}


def response(level_probs=(0, 0, 1, 0, 0), confidence=0.8, risks=None, target="route", **extra):
    answers = {"level": {"type": "score", "score": 2.0, "confidence": confidence,
                         "probabilities": {str(i): p for i, p in enumerate(level_probs)}}}
    if target is not None:
        answers["target"] = {"type": "choice", "choice": target}
    answers.update({f: {"type": "noul", "noul": v} for f, v in {**dict.fromkeys(RISK_FLAGS, 0.0), **(risks or {})}.items()})
    return {"model": "jev-1.13.0", "answers": answers, "usage": {"input_tokens": 392, "output_tokens": 65}, **extra}


class FakeTransport:
    def __init__(self, body=None, status=200, text=None, exc=None):
        self.text = text if text is not None else json.dumps(body if body is not None else response())
        self.status, self.exc, self.calls = status, exc, []

    def __call__(self, url, headers, body, timeout_s):
        self.calls.append((url, headers, json.loads(body), timeout_s))
        if self.exc:
            raise self.exc
        return self.status, self.text


def run(transport, task="Fix the bug", paths=(), env=ENV, timeout_s=7, **kw):
    b = JevBackend(transport, env=env, **kw)
    return b, b.classify(DifficultyInput(task, tuple(paths)), timeout_s)


class RequestTest(unittest.TestCase):
    def test_request_shape(self):
        t = FakeTransport()
        run(t, "Fix it", ["a.py"], timeout_s=7)
        url, headers, body, timeout = t.calls[0]
        self.assertEqual((url, timeout), (URL, 7))
        self.assertEqual(headers["Authorization"], f"Bearer {FAKE_CRED}")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(body["model"], "jev-latest")
        self.assertIn("Fix it", body["state"])
        self.assertIn("a.py", body["state"])
        q = body["questions"]
        self.assertEqual(q["level"]["type"], "score")
        self.assertEqual(len(q["level"]["criteria"]), 5)
        for f in ("security", "auth", "payment", "data_migration", "data_loss", "concurrency"):
            self.assertEqual(q[f]["type"], "noul")

    def test_state_is_truncated(self):
        t = FakeTransport()
        run(t, "x" * (MAX_TASK_CHARS + 500), [f"p{i}.py" for i in range(MAX_PATHS + 10)])
        state = t.calls[0][2]["state"]
        self.assertNotIn("x" * (MAX_TASK_CHARS + 1), state)
        self.assertIn(f"p{MAX_PATHS - 1}.py", state)
        self.assertNotIn(f"p{MAX_PATHS}.py", state)

    def test_model_env_override_and_constructor(self):
        t = FakeTransport()
        run(t, env={**ENV, MODEL_ENV: "jev-1.13.0"})
        self.assertEqual(t.calls[0][2]["model"], "jev-1.13.0")
        t = FakeTransport()
        run(t, env={**ENV, MODEL_ENV: "jev-1.13.0"}, model="jev-x")
        self.assertEqual(t.calls[0][2]["model"], "jev-x")

    def test_factory_needs_no_key_or_network(self):
        self.assertEqual(BACKENDS["jev"]().name, "jev")


class MappingTest(unittest.TestCase):
    def test_level_argmax_distribution_confidence(self):
        _, d = run(FakeTransport(response((0.1, 0.1, 0.6, 0.1, 0.1))))
        self.assertEqual((d.level, d.backend, d.confidence), ("L3", "jev", 0.8))
        self.assertAlmostEqual(sum(d.distribution.values()), 1.0)
        self.assertEqual(d.distribution["L3"], 0.6)
        self.assertEqual(d.reason_codes, ("jev", "jev-1.13.0"))

    def test_tie_picks_higher_level(self):
        _, d = run(FakeTransport(response((0, 0.5, 0, 0.5, 0))))
        self.assertEqual(d.level, "L4")

    def test_distribution_renormalized(self):
        _, d = run(FakeTransport(response((0.1, 0.1, 0.1, 0.1, 0.1))))  # sums 0.5
        self.assertAlmostEqual(sum(d.distribution.values()), 1.0)

    def test_risk_flag_threshold_and_bool(self):
        _, d = run(FakeTransport(response(risks={"auth": 0.5, "security": 0.49, "payment": True, "data_loss": False})))
        self.assertEqual(d.risk_flags, ("auth", "payment"))

    def test_raw_risk_scores_kept_and_per_flag_threshold(self):
        b, d = run(FakeTransport(response(risks={"security": 0.7, "auth": 0.95})))
        self.assertEqual((b.last_risk_scores["security"], b.last_risk_scores["auth"]), (0.7, 0.95))
        self.assertEqual(d.risk_flags, ("auth",))  # calibrated security threshold 0.85
        with mock.patch.dict(jev.RISK_THRESHOLDS, {"security": 0.6}):
            _, d = run(FakeTransport(response(risks={"security": 0.7, "auth": 0.95})))
        self.assertEqual(d.risk_flags, ("security", "auth"))

    def test_unverified_shapes_fail_closed(self):
        """Only the documented shape is trusted: other keys/scales raise instead of silently shifting the level."""
        for probs in ({str(i): 0.2 for i in range(1, 6)},  # 1-based keys
                      {"0": 0.5, "1": 0.5},  # missing levels
                      {str(i): 0 for i in range(5)}):  # all zero
            body = response()
            body["answers"]["level"] = {"probabilities": probs, "score": 2.0}
            with self.subTest(probs=probs), self.assertRaises(ValueError):
                run(FakeTransport(body))
        body = response()
        body["answers"]["level"] = {"score": 2.0}
        with self.assertRaises(ValueError):  # score alone: scale unverified
            run(FakeTransport(body))
        for bad in ("yes", None, 1.5):
            body = response()
            body["answers"]["auth"] = {"type": "noul", "noul": bad}
            with self.subTest(noul=bad), self.assertRaises(ValueError):
                run(FakeTransport(body))
        body = response()
        del body["answers"]["concurrency"]
        with self.assertRaises(ValueError):  # a missing risk answer never passes silently
            run(FakeTransport(body))

    def test_usage_kept_when_answers_unusable(self):
        b = JevBackend(FakeTransport({"answers": {}, "usage": {"input_tokens": 9, "output_tokens": 1}}), env=ENV)
        with self.assertRaises(ValueError):
            b.classify(DifficultyInput("x"), 5)
        self.assertEqual(b.last_usage, {"input_tokens": 9, "output_tokens": 1})

    def test_out_of_range_confidence_dropped(self):
        _, d = run(FakeTransport(response(confidence=1.7)))
        self.assertIsNone(d.confidence)

    def test_usage_reported_and_reset(self):
        b, _ = run(FakeTransport())
        self.assertEqual(b.last_usage, {"input_tokens": 392, "output_tokens": 65})
        b._transport = FakeTransport(status=500)
        with self.assertRaises(RuntimeError):
            b.classify(DifficultyInput("x"), 5)
        self.assertIsNone(b.last_usage)


class TargetTest(unittest.TestCase):
    def test_question_asks_for_the_four_targets_with_descriptions(self):
        q = jev.QUESTIONS["target"]
        self.assertEqual(q["type"], "choice")
        self.assertIsInstance(q["criteria"], dict)  # a list is rejected by the API with HTTP 422 (seen live)
        self.assertEqual(list(q["criteria"]), ["route", "plan_only", "review_only", "no_route"])
        text = " ".join(q["criteria"].values())
        for needle in ("review-and-fix", "wait for approval", "question", "no code or software context"):
            self.assertIn(needle, text)

    def test_choice_maps_to_decision_target(self):
        self.assertTrue(JevBackend.provides_target)
        for t in ("route", "plan_only", "review_only", "no_route"):
            with self.subTest(t=t):
                self.assertEqual(run(FakeTransport(response(target=t)))[1].target, t)

    def test_criterion_text_is_not_a_valid_answer(self):
        body = response()
        body["answers"]["target"]["choice"] = jev.TARGET_CRITERIA["plan_only"]
        with self.assertRaises(ValueError):
            run(FakeTransport(body))

    def test_unknown_missing_or_malformed_choice_fails_closed(self):
        for bad in ("ROUTE", "maybe", None, 2, ["route"]):
            body = response()
            body["answers"]["target"] = {"type": "choice", "choice": bad}
            with self.subTest(choice=bad), self.assertRaises(ValueError):
                run(FakeTransport(body))
        for ans in (None, "route", {}):
            body = response(target=None)
            if ans is not None:
                body["answers"]["target"] = ans
            with self.subTest(answer=ans), self.assertRaises(ValueError):
                run(FakeTransport(body))

    def test_usage_still_recorded_when_the_target_answer_is_unusable(self):
        b = JevBackend(FakeTransport(response(target="bogus")), env=ENV)
        with self.assertRaises(ValueError):
            b.classify(DifficultyInput("x"), 5)
        self.assertEqual(b.last_usage, {"input_tokens": 392, "output_tokens": 65})

    def test_target_survives_risk_merge(self):
        self.assertEqual(run(FakeTransport(response(target="plan_only")))[1].with_risk_flags(["auth"]).target, "plan_only")


class LiveShapeTest(unittest.TestCase):
    def test_recorded_live_response_maps(self):
        """Recorded once from jev-latest (2026-10-01, pilot L4 auth task): the shape the mapping relies on."""
        body = json.loads((Path(__file__).resolve().parent / "fixtures" / "jev" / "live-l4-auth.json").read_text())
        with self.assertRaises(ValueError):  # recorded before the target question existed: fail closed
            run(FakeTransport(body))
        body["answers"]["target"] = {"type": "choice", "choice": "route"}  # synthetic: the live file stays untouched
        b, d = run(FakeTransport(body))
        self.assertEqual((d.level, d.confidence, d.risk_flags, d.target), ("L3", 0.49, ("security", "auth"), "route"))
        self.assertAlmostEqual(d.distribution["L2"], 0.33)
        self.assertEqual(d.reason_codes, ("jev", "jev-1.13.0"))
        self.assertEqual(b.last_usage, {"input_tokens": 541, "output_tokens": 119})
        legend = body["answers"]["level"]["legend"]  # criteria are echoed in our order: index i == L(i+1)
        self.assertEqual([legend[str(i)] for i in range(5)], list(jev.QUESTIONS["level"]["criteria"]))


class FailureTest(unittest.TestCase):
    def assertFails(self, transport, env=ENV):
        with self.assertRaises(Exception) as cm:
            run(transport, env=env)
        self.assertNotIn(FAKE_CRED, str(cm.exception))
        return cm.exception

    def test_missing_key_names_variable_only(self):
        t = FakeTransport()
        exc = self.assertFails(t, env={})
        self.assertIn(KEY_ENV, str(exc))
        self.assertEqual(t.calls, [])

    def test_non_2xx(self):
        for status in (401, 429, 500):
            self.assertFails(FakeTransport(status=status))

    def test_timeout_and_network(self):
        self.assertFails(FakeTransport(exc=TimeoutError("slow")))
        self.assertFails(FakeTransport(exc=OSError("down")))

    def test_bad_payloads(self):
        for text in ("not json", "[]", "{}", '{"answers": {}}', '{"answers": {"level": 3}}',
                     '{"answers": {"level": {}}}', '{"answers": {"level": {"probabilities": {"0": "x"}}}}'):
            self.assertFails(FakeTransport(text=text))


class IntegrationTest(unittest.TestCase):
    def test_router_falls_back_to_subscription_on_jev_failure(self):
        jev = JevBackend(FakeTransport(status=500), env=ENV)
        sub = mock.Mock(return_value=DifficultyDecision("L2", "subscription"))
        reg = {"jev": lambda: jev, "subscription": SubscriptionBackend}
        cfg = {"difficulty": {"backend": "jev", "fallback": "subscription"}}
        with mock.patch.object(SubscriptionBackend, "classify", sub):
            plan = route("Fix the discount bug in pricing.py", repo_config=cfg, registry=reg)
        self.assertEqual((plan.decision.level, plan.decision.backend), ("L2", "subscription"))
        self.assertEqual(sub.call_count, 1)

    def test_router_uses_jev_and_reports_usage(self):
        jev = JevBackend(FakeTransport(response((0, 0, 0, 1, 0))), env=ENV)
        plan = route("Fix the discount bug in pricing.py", registry={"jev": lambda: jev},
                     repo_config={"difficulty": {"backend": "jev"}})
        self.assertEqual((plan.decision.level, plan.classifier_usage["input_tokens"]), ("L4", 392))


class DryRunJevTest(CliCase):
    def test_dry_run_refuses_jev_without_level_or_classify(self):
        (self.cwd / ".model-effort-router.json").write_text('{"difficulty": {"backend": "jev"}}')
        with mock.patch.object(JevBackend, "classify", side_effect=AssertionError("jev called")) as m:
            rc, _ = self.mer("Fix the discount bug in pricing.py", "--dry-run")
            self.assertEqual((rc, m.call_count), (2, 0))
            rc, _ = self.mer("Fix the login auth check in auth.py", "--dry-run", "--level", "L3")
            self.assertEqual((rc, m.call_count), (0, 0))


if __name__ == "__main__":
    unittest.main()


class DefaultTransportTest(unittest.TestCase):
    """Local 127.0.0.1 servers only: never the real API."""

    def serve(self, handler):
        import http.server
        import threading
        srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_address[1]}"

    def test_redirect_is_refused_and_never_carries_the_key(self):
        import http.server
        seen = []

        class Sink(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                seen.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *a):
                pass

        sink = self.serve(Sink)

        class Redirect(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(302)
                self.send_header("Location", sink + "/stolen")
                self.end_headers()

            def log_message(self, *a):
                pass

        status, _ = jev.default_transport(self.serve(Redirect), {"Authorization": f"Bearer {FAKE_CRED}"}, b"{}", 5)
        self.assertEqual((status, seen), (302, []))

    def test_total_deadline_even_when_the_body_trickles(self):
        import http.server
        import time

        class Slow(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Length", "100")
                self.end_headers()
                for _ in range(20):  # each byte arrives before the per-read timeout, the whole body does not
                    self.wfile.write(b" ")
                    self.wfile.flush()
                    time.sleep(0.2)

            def log_message(self, *a):
                pass

        t0 = time.monotonic()
        with self.assertRaises(TimeoutError):
            jev.default_transport(self.serve(Slow), {}, b"{}", 1)
        self.assertLess(time.monotonic() - t0, 2)

import socket
import unittest
import urllib.request
from unittest import mock

from model_effort_router.difficulty import jev, nimble
from model_effort_router.difficulty.decision import DifficultyDecision, DifficultyInput
from model_effort_router.difficulty.nimble import DEFAULT_URL, NimbleBackend, check_local_url, validate_options
from model_effort_router.difficulty.registry import BACKENDS, create
from model_effort_router.difficulty.subscription import SubscriptionBackend
from model_effort_router.policy.config import resolve_config
from model_effort_router.policy.router import route
from tests.test_jev import FakeTransport, response

TASK = "Fix the discount bug in pricing.py"


def run(transport, env=None, options=None, **kw):
    b = NimbleBackend(transport, env={} if env is None else env, options=options, **kw)
    return b, b.classify(DifficultyInput(TASK), 7)


class RequestTest(unittest.TestCase):
    def test_local_url_no_auth_header_no_key_needed(self):
        t = FakeTransport(response())
        run(t)
        url, headers, body, timeout = t.calls[0]
        self.assertEqual((url, timeout), (DEFAULT_URL, 7))
        self.assertEqual(DEFAULT_URL, "http://127.0.0.1:11434/v1/systemone")  # the address: no resolver dependence
        self.assertEqual(headers, {"Content-Type": "application/json"})  # nothing that looks like a credential
        self.assertEqual((body["model"], body["questions"]), ("nimble", jev.QUESTIONS))
        self.assertIn(TASK, body["state"])

    def test_a_typesafe_key_in_the_env_is_never_sent(self):
        t = FakeTransport(response())
        run(t, env={"TYPESAFE_API_KEY": "fake-cred-value-123"})
        self.assertNotIn("Authorization", t.calls[0][1])
        self.assertNotIn("fake-cred-value-123", str(t.calls[0]))


class PrecedenceTest(unittest.TestCase):
    def sent(self, env=None, options=None, **kw):
        t = FakeTransport(response())
        run(t, env, options, **kw)
        return t.calls[0][0], t.calls[0][2]["model"]

    def test_default_then_env_then_config(self):
        self.assertEqual(self.sent(), (DEFAULT_URL, "nimble"))
        env = {"MER_NIMBLE_MODEL": "nimble:9b", "MER_NIMBLE_URL": "http://127.0.0.1:9999/v1/systemone"}
        self.assertEqual(self.sent(env), ("http://127.0.0.1:9999/v1/systemone", "nimble:9b"))
        opts = {"model": "nimble:2b", "url": "http://localhost:1234/v1/systemone"}
        self.assertEqual(self.sent(env, opts), ("http://localhost:1234/v1/systemone", "nimble:2b"))
        self.assertEqual(self.sent(env, {"model": "nimble:2b"}), ("http://127.0.0.1:9999/v1/systemone", "nimble:2b"))  # per key
        self.assertEqual(self.sent(env, opts, model="explicit"), ("http://localhost:1234/v1/systemone", "explicit"))

    def test_config_reaches_the_backend_through_the_router(self):
        t = FakeTransport(response())
        seen = []

        def classify(self, task, timeout_s):
            seen.append(self._options)
            return DifficultyDecision("L2", "nimble")

        cfg = {"difficulty": {"backend": "nimble", "nimble": {"model": "nimble:2b", "risk_thresholds": {"auth": 0.1}}}}
        with mock.patch.object(NimbleBackend, "classify", classify):
            route(TASK, repo_config=cfg, registry={"nimble": NimbleBackend})
            route(TASK, repo_config={"difficulty": {"backend": "nimble"}}, registry={"nimble": NimbleBackend})
        self.assertEqual(seen, [{"model": "nimble:2b", "risk_thresholds": {"auth": 0.1}}, {}])
        # only the real NimbleBackend gets options: any other factory (a stand-in, a double) is called without them
        made = []
        reg = {"nimble": lambda **kw: made.append(kw) or NimbleBackend(t, env={})}
        plan = route(TASK, repo_config=cfg, registry=reg)
        self.assertEqual(made, [{}])
        self.assertEqual((plan.decision.backend, plan.decision.reason_codes[0]), ("nimble", "nimble"))
        self.assertEqual(t.calls[0][2]["model"], "nimble")  # the options did not reach the double


class LoopbackTest(unittest.TestCase):
    def test_loopback_hosts_accepted(self):
        for url in ("http://localhost:11434/v1/systemone", "http://127.0.0.1/v1/systemone", "http://[::1]:11434/x",
                    "https://localhost:8443/v1/systemone"):
            self.assertEqual(check_local_url(url), url)

    def test_everything_else_raises_before_anything_is_sent(self):
        bad = ["https://api.typesafe.ai/v1/systemone", "http://example.com/v1/systemone", "http://10.0.0.5:11434/x",
               "http://localhost.evil.com/x", "http://evil.com/?h=localhost", "http://localhost@evil.com/x",
               "http://user:pw@localhost/x", "file:///etc/passwd", "ftp://localhost/x", "localhost:11434/x", "", "http://[::1/x",
               "http://127.0.0.2/x", "http://0.0.0.0/x"]
        for url in bad:
            t = FakeTransport(response())
            with self.subTest(url=url), self.assertRaises(ValueError):
                run(t, options={"url": url})
            self.assertEqual(t.calls, [], url)
        t = FakeTransport(response())
        with self.assertRaises(ValueError):  # a typo in the env is guarded as well
            run(t, env={"MER_NIMBLE_URL": "http://example.com/v1/systemone"})
        self.assertEqual(t.calls, [])

    def test_local_opener_ignores_proxies_and_refuses_redirects(self):
        # the empty ProxyHandler replaces urllib's default (environment-driven) one and registers no proxy opener
        self.assertEqual([h for h in nimble._LOCAL_OPENER.handlers if isinstance(h, urllib.request.ProxyHandler)], [])
        self.assertTrue([h for h in nimble._LOCAL_OPENER.handlers if isinstance(h, jev._RefuseRedirect)])

    def test_real_transport_connection_refused_on_a_closed_loopback_port(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        with mock.patch.dict("os.environ", {"http_proxy": "http://203.0.113.9:3128", "HTTP_PROXY": "http://203.0.113.9:3128"}):
            with self.assertRaises(OSError):  # never reaches the proxy address above: that would hang or leave the machine
                nimble.local_transport(f"http://127.0.0.1:{port}/v1/systemone", {}, b"{}", 5)


class ParseTest(unittest.TestCase):
    def test_decision_target_usage_and_reason_codes(self):
        b, d = run(FakeTransport(response((0, 1, 0, 0, 0), confidence=0.7, risks={"auth": 0.9}, target="plan_only")))
        self.assertEqual((d.level, d.backend, d.target, d.risk_flags, d.confidence), ("L2", "nimble", "plan_only", ("auth",), 0.7))
        self.assertEqual(d.reason_codes, ("nimble", "jev-1.13.0"))  # "nimble" + the response model
        self.assertEqual(b.last_usage, {"input_tokens": 392, "output_tokens": 65})
        self.assertTrue(b.calls_model and b.provides_target)

    def test_default_tuning_is_jevs_and_l4_demotion_uses_the_nimble_code(self):
        self.assertEqual(nimble.NIMBLE_RISK_THRESHOLDS, jev.RISK_THRESHOLDS)
        _, d = run(FakeTransport(response((0, 0, 0.3, 0.4, 0.3))))  # P(L4)+P(L5) = 0.7 >= 0.6: stays L4
        self.assertEqual((d.level, "nimble_l4_unsure" in d.reason_codes), ("L4", False))
        _, d = run(FakeTransport(response((0.2, 0.2, 0.2, 0.25, 0.15))))  # argmax L4, 0.4 < 0.6: demoted
        self.assertEqual((d.level, "nimble_l4_unsure" in d.reason_codes, "jev_l4_unsure" in d.reason_codes), ("L3", True, False))

    def test_options_override_thresholds_and_l4_rules(self):
        body = response(risks={"security": 0.7})
        self.assertEqual(run(FakeTransport(body))[1].risk_flags, ("security",))  # Jev default 0.6
        opts = {"risk_thresholds": {"security": 0.9}}
        self.assertEqual(run(FakeTransport(body), options=opts)[1].risk_flags, ())
        l4 = response((0, 0, 0.1, 0.5, 0.4))  # P(L4)+P(L5) = 0.9
        self.assertEqual(run(FakeTransport(l4), options={"l4_min_prob": 0.95})[1].level, "L3")
        self.assertEqual(run(FakeTransport(l4))[1].level, "L4")
        flagged = response((0, 0, 0.3, 0.4, 0.3), risks={"concurrency": 0.95})  # 0.7: concurrency needs 0.8 by default
        self.assertEqual(run(FakeTransport(flagged))[1].level, "L3")
        self.assertEqual(run(FakeTransport(flagged), options={"l4_min_prob_by_flag": {"concurrency": 0.5}})[1].level, "L4")

    def test_malformed_answers_fail_closed_and_name_nimble(self):
        for body in ({"answers": {}}, response(target="bogus")):
            with self.subTest(body=str(body)[:30]), self.assertRaises(ValueError) as cm:
                run(FakeTransport(body))
            self.assertIn("nimble", str(cm.exception))
        with self.assertRaises(RuntimeError) as cm:
            run(FakeTransport(status=404))
        self.assertIn("nimble HTTP 404", str(cm.exception))


class ConfigTest(unittest.TestCase):
    def test_valid_config_resolves_and_defaults_to_none(self):
        self.assertIsNone(resolve_config().nimble)
        cfg = {"difficulty": {"backend": "nimble", "nimble": {
            "model": "nimble", "url": "http://localhost:11434/v1/systemone", "risk_thresholds": {"auth": 0.5},
            "l4_min_prob": 0.6, "l4_min_prob_by_flag": {"concurrency": 0.8}}}}
        self.assertEqual(resolve_config(repo=cfg, registry=BACKENDS).nimble, cfg["difficulty"]["nimble"])

    def test_repo_beats_user(self):
        user = {"difficulty": {"nimble": {"model": "user-model"}}}
        repo = {"difficulty": {"nimble": {"model": "repo-model"}}}
        self.assertEqual(resolve_config(repo=repo, user=user).nimble, {"model": "repo-model"})
        self.assertEqual(resolve_config(user=user).nimble, {"model": "user-model"})

    def test_invalid_options_are_config_errors(self):
        bad = [{"nope": 1}, {"risk_thresholds": {"typo": 0.5}}, {"l4_min_prob_by_flag": {"typo": 0.5}},
               {"risk_thresholds": {"auth": 1.5}}, {"risk_thresholds": {"auth": -0.1}}, {"risk_thresholds": {"auth": True}},
               {"risk_thresholds": {"auth": "0.5"}}, {"risk_thresholds": [0.5]}, {"l4_min_prob": 2}, {"l4_min_prob": None},
               {"l4_min_prob_by_flag": {"concurrency": 9}}, {"model": ""}, {"model": 3}, {"url": None}, "x", []]
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                resolve_config(repo={"difficulty": {"nimble": raw}})
            with self.assertRaises(ValueError):
                validate_options(raw)

    def test_boundaries_and_empty_object_are_valid(self):
        self.assertEqual(validate_options({}), {})
        self.assertEqual(validate_options({"l4_min_prob": 0, "risk_thresholds": {"auth": 1}}),
                         {"l4_min_prob": 0, "risk_thresholds": {"auth": 1}})

    def test_a_non_loopback_config_url_is_a_config_error_up_front(self):
        for url in ("http://example.com/x", "https://api.typesafe.ai/v1/systemone", "file:///x", "http://localhost@evil.com/"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                resolve_config(repo={"difficulty": {"nimble": {"url": url}}})
        ok = {"url": "http://localhost:9/x"}
        self.assertEqual(resolve_config(repo={"difficulty": {"nimble": ok}}).nimble, ok)  # any loopback port

    def test_the_send_time_check_remains_for_env_and_direct_options(self):
        t = FakeTransport(response())
        with self.assertRaises(ValueError):
            NimbleBackend(t, env={"MER_NIMBLE_URL": "http://example.com/x"}).classify(DifficultyInput(TASK), 5)
        self.assertEqual(t.calls, [])


class DryRunAndCompareTest(unittest.TestCase):
    def test_dry_run_level_with_nimble_options_gives_that_level_not_the_default(self):
        import io
        import json
        import tempfile
        from pathlib import Path
        from model_effort_router import cli
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".model-effort-router.json").write_text(json.dumps(
                {"difficulty": {"backend": "nimble", "nimble": {"model": "nimble:2b", "l4_min_prob": 0.7}}}))
            out = io.StringIO()
            rc = cli.main(["run", "--cwd", d, "--dry-run", "--level", "L4", "Fix the login check in auth.py"],
                          env={"HOME": d, "MER_STATE_DIR": d}, out=out)
        self.assertEqual(rc, 0)
        self.assertIn("level: L4", out.getvalue())

    def test_compare_threads_the_cwd_nimble_options(self):
        import contextlib
        import io
        import json
        import os
        import tempfile
        from pathlib import Path
        from evaluation import compare
        seen = []

        def factory(**kw):
            seen.append(kw)
            return type("Stub", (), {"name": "nimble", "classify": lambda self, task, t: DifficultyDecision("L2", "nimble")})()

        case = {"id": "c", "task": TASK, "paths": [], "status": "adjudicated",
                "labels": [{"labeler": w, "level": "L2", "risk_flags": [], "target": "route"} for w in ("a", "b")],
                "final": {"level": "L2", "risk_flags": [], "target": "route"}}
        with tempfile.TemporaryDirectory() as d:
            corpus = Path(d) / "c.jsonl"
            corpus.write_text(json.dumps(case))
            cfg = Path(d) / ".model-effort-router.json"
            old = os.getcwd()
            try:
                os.chdir(d)
                with mock.patch.object(compare, "NimbleBackend", factory), contextlib.redirect_stdout(io.StringIO()):
                    with mock.patch.dict(os.environ, {"HOME": d, "MER_USER_CONFIG": str(Path(d) / "none.json")}):
                        compare.main(["--corpus", str(corpus), "--backends", "nimble", "--live"], registry={"nimble": factory})
                        cfg.write_text(json.dumps({"difficulty": {"nimble": {"model": "nimble:2b"}}}))
                        compare.main(["--corpus", str(corpus), "--backends", "nimble", "--live"], registry={"nimble": factory})
                        cfg.write_text(json.dumps({"difficulty": {"nimble": {"url": "http://example.com/x"}}}))
                        with contextlib.redirect_stderr(io.StringIO()):
                            self.assertEqual(compare.main(["--corpus", str(corpus), "--backends", "nimble", "--live"],
                                                          registry={"nimble": factory}), 2)
            finally:
                os.chdir(old)
        self.assertEqual(seen, [{}, {"options": {"model": "nimble:2b"}}])


class RegistryAndFallbackTest(unittest.TestCase):
    def test_registered_and_created_with_and_without_options(self):
        self.assertIs(BACKENDS["nimble"], NimbleBackend)
        self.assertEqual(create("nimble")._options, {})
        self.assertEqual(create("nimble", options={"model": "m"})._options, {"model": "m"})
        self.assertIsNone(getattr(create("jev"), "_options", None))

    def test_connection_refused_falls_back_to_subscription(self):
        nb = NimbleBackend(FakeTransport(exc=ConnectionRefusedError("refused")), env={})
        sub = mock.Mock(return_value=DifficultyDecision("L2", "subscription"))
        reg = {"nimble": lambda **kw: nb, "subscription": SubscriptionBackend}
        cfg = {"difficulty": {"backend": "nimble", "fallback": "subscription"}}
        with mock.patch.object(SubscriptionBackend, "classify", sub):
            plan = route(TASK, repo_config=cfg, registry=reg)
        self.assertEqual((plan.decision.backend, plan.decision.level), ("subscription", "L2"))
        self.assertIn("fallback_cause:nimble:ConnectionRefusedError", plan.decision.reason_codes)

    def test_non_loopback_url_falls_back_without_sending(self):
        t = FakeTransport(response())
        nb = NimbleBackend(t, env={"MER_NIMBLE_URL": "http://example.com/v1/systemone"})
        sub = mock.Mock(return_value=DifficultyDecision("L2", "subscription"))
        with mock.patch.object(SubscriptionBackend, "classify", sub):
            plan = route(TASK, repo_config={"difficulty": {"backend": "nimble", "fallback": "subscription"}},
                         registry={"nimble": lambda **kw: nb, "subscription": SubscriptionBackend})
        self.assertEqual((t.calls, plan.decision.backend), ([], "subscription"))

    def test_route_logs_usage_like_jev(self):
        nb = NimbleBackend(FakeTransport(response()), env={})
        plan = route(TASK, repo_config={"difficulty": {"backend": "nimble"}}, registry={"nimble": lambda **kw: nb})
        self.assertEqual((plan.classifier_usage["input_tokens"], plan.classifier_usage["output_tokens"]), (392, 65))
        self.assertFalse(plan.classifier_usage_missing)

    def test_compare_and_live_runner_accept_nimble(self):
        from evaluation import compare, live_runner
        self.assertIn("nimble", compare.LIVE_BACKENDS)  # it calls a model: --live is required
        self.assertEqual(compare.main(["--corpus", "x", "--backends", "nimble"]), 2)
        self.assertIn("nimble", sorted(live_runner.BACKENDS))


if __name__ == "__main__":
    unittest.main()

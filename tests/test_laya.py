import io
import json
import threading
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from model_effort_router.cli import main
from model_effort_router.difficulty.decision import DifficultyDecision, DifficultyInput
from model_effort_router.difficulty.jev import QUESTIONS, JevBackend
from model_effort_router.difficulty.nimble import NimbleBackend
from model_effort_router.difficulty.registry import BACKENDS
from model_effort_router.difficulty.subscription import BackendOutputError
from model_effort_router.difficulty.laya import DEFAULT_MODEL, DEFAULT_URL, LayaBackend
from model_effort_router.policy.config import RouterConfig, resolve_config
from model_effort_router.policy.router import route
from tests.test_jev import FakeTransport, response


class LayaTest(unittest.TestCase):
    def test_compact_questions_preserve_criteria_context_and_other_backends(self):
        task = DifficultyInput("진행", context="Implement the approved parser changes.")
        original = json.loads(json.dumps(QUESTIONS))
        transport = FakeTransport()
        LayaBackend(transport=transport, env={}).classify(task, 1)
        body = transport.calls[0][2]
        self.assertIn(task.context, body["state"])
        for name, question in body["questions"].items():
            self.assertEqual(question["criteria"], original[name]["criteria"])
            self.assertLess(len(question["instructions"]), len(original[name]["instructions"]))
            for rule in ("current request", "session context", "prior plan", "role and effort"):
                self.assertIn(rule, question["instructions"])
        for backend_type, env in ((JevBackend, {"TYPESAFE_API_KEY": "test-key"}), (NimbleBackend, {})):
            transport = FakeTransport()
            backend_type(transport=transport, env=env).classify(task, 1)
            for name in original:
                self.assertEqual(transport.calls[0][2]["questions"][name], original[name])
        self.assertEqual(QUESTIONS, original)

    def test_invalid_options_are_rejected_by_backend_and_config(self):
        for options in (
            [],
            False,
            0,
            "",
            {"unknown": True},
            {"model": " "},
            {"url": 8000},
            {"url": "file:///tmp/x"},
            {"url": "http://localhost.evil/x"},
            {"url": "http://user:pass@localhost/x"},
            {"url": "http://[invalid/x"},
        ):
            with self.subTest(options=options):
                with self.assertRaisesRegex(ValueError, "laya"):
                    LayaBackend(options=options)
                with self.assertRaisesRegex(ValueError, "laya"):
                    resolve_config(repo={"difficulty": {"laya": options}})

    def test_context_positional_arguments_remain_compatible(self):
        cfg = RouterConfig("auto", "laya", "none", 10, {}, None, False, 500)
        self.assertEqual((cfg.context_enabled, cfg.context_max_chars, cfg.laya), (False, 500, None))

    def test_environment_and_unauthenticated_defaults(self):
        for env, url, model in (
            ({}, DEFAULT_URL, DEFAULT_MODEL),
            (
                {"MER_LAYA_URL": "http://localhost:8001/v1/systemone", "MER_LAYA_MODEL": "custom"},
                "http://localhost:8001/v1/systemone",
                "custom",
            ),
        ):
            with self.subTest(env=env):
                transport = FakeTransport(response(target="no_route"))
                decision = LayaBackend(transport=transport, env=env).classify(DifficultyInput("x"), 1)
                self.assertEqual((transport.calls[0][0], transport.calls[0][2]["model"]), (url, model))
                self.assertEqual(transport.calls[0][1], {"Content-Type": "application/json"})
                self.assertEqual((LayaBackend.provides_target, decision.target), (False, None))

    def test_defaults_and_optional_bearer(self):
        transport = FakeTransport(response(usage={"input_tokens": 12, "output_tokens": 0}))
        backend = LayaBackend(transport=transport, env={"MER_LAYA_API_KEY": "secret"})
        decision = backend.classify(DifficultyInput("Fix pricing"), 3)
        url, headers, body, timeout = transport.calls[0]
        self.assertEqual((url, body["model"], timeout), (DEFAULT_URL, DEFAULT_MODEL, 3))
        self.assertEqual(headers["Authorization"], "Bearer secret")
        self.assertEqual(set(body["questions"]), {"role", "effort"})
        self.assertEqual((decision.role, decision.effort), ("fix", "medium"))
        self.assertEqual(backend.last_usage, {"input_tokens": 12, "output_tokens": 0})

    def test_config_precedes_environment_and_config_rejects_external_url(self):
        transport = FakeTransport()
        LayaBackend(
            transport=transport,
            env={"MER_LAYA_MODEL": "env", "MER_LAYA_URL": "http://localhost:8001/v1/systemone"},
            options={"model": "local", "url": "http://127.0.0.1:9000/v1/systemone"},
        ).classify(DifficultyInput("x"), 1)
        self.assertEqual(
            (transport.calls[0][0], transport.calls[0][2]["model"]), ("http://127.0.0.1:9000/v1/systemone", "local")
        )
        with self.assertRaises(ValueError):
            LayaBackend(options={"url": "https://remote.example/v1/systemone"})

    def test_config_and_registry_support_laya_as_primary_or_fallback(self):
        self.assertIs(BACKENDS["laya"], LayaBackend)
        cfg = resolve_config(repo={"difficulty": {"backend": "laya", "laya": {"model": "custom"}}})
        self.assertEqual(cfg.laya, {"model": "custom"})
        local = LayaBackend(transport=FakeTransport(exc=ConnectionRefusedError()), env={})
        backup = mock.Mock(name="backup")
        backup.name, backup.calls_model, backup.last_usage = "backup", True, None
        backup.classify.return_value = DifficultyDecision("fix", "medium", "backup")
        plan = route(
            "x",
            repo_config={"difficulty": {"backend": "laya", "fallback": "backup"}},
            registry={"laya": lambda **kw: local, "backup": lambda: backup},
            explicit=True,
        )
        self.assertEqual(plan.decision.backend, "backup")

        transport = FakeTransport()
        backup.classify.side_effect = ConnectionRefusedError()
        plan = route(
            "x",
            repo_config={
                "difficulty": {
                    "backend": "backup",
                    "fallback": "laya",
                    "laya": {"model": "configured", "url": "http://localhost:9001/v1/systemone"},
                }
            },
            registry={"backup": lambda: backup, "laya": lambda **kw: LayaBackend(transport=transport, env={}, **kw)},
            explicit=True,
        )
        self.assertEqual(plan.decision.backend, "laya")
        self.assertEqual(
            (transport.calls[0][0], transport.calls[0][2]["model"]),
            ("http://localhost:9001/v1/systemone", "configured"),
        )

    def test_local_http_server_receives_systemone_contract(self):
        received = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received["path"] = self.path
                received["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                payload = json.dumps(response()).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                Path(directory, ".model-effort-router.json").write_text(
                    json.dumps(
                        {
                            "difficulty": {
                                "backend": "laya",
                                "laya": {"url": f"http://127.0.0.1:{server.server_port}/v1/systemone"},
                            }
                        }
                    )
                )
                output = io.StringIO()
                with mock.patch.dict("os.environ", {}, clear=True):
                    status = main(
                        ["route", "--json", "--host", "codex", "--cwd", directory, "Fix local task"],
                        env={"MER_USER_CONFIG": str(Path(directory, "absent.json"))},
                        out=output,
                    )
                self.assertEqual(status, 0)
                result = json.loads(output.getvalue())
                self.assertEqual((result["classifier"], result["role"], result["effort"]), ("laya", "fix", "medium"))
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
        self.assertEqual(received["path"], "/v1/systemone")
        self.assertEqual(received["body"]["model"], DEFAULT_MODEL)
        self.assertEqual(set(received["body"]["questions"]), {"role", "effort"})

    def test_malformed_and_http_error_fail_for_chain(self):
        for transport in (FakeTransport(body={"answers": {}}), FakeTransport(status=503)):
            with self.subTest(transport=transport), self.assertRaises((RuntimeError, BackendOutputError)):
                LayaBackend(transport=transport, env={}).classify(DifficultyInput("x"), 1)


if __name__ == "__main__":
    unittest.main()

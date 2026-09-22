import contextlib
import http.server
import io
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import classifier
import jev_provider
import rules
import route_reuse
import router
from rules import FACTS


BASE_FACTS = {
    "mechanical_only": "no",
    "files_touched": "1",
    "crosses_module_boundary": "no",
    "crosses_service_boundary": "no",
    "fix_or_result_known": "yes",
    "intermittent_or_concurrency": "no",
    "needs_new_structure": "no",
    "changes_security_or_payment_logic": "no",
    "reviews_security_sensitive_code": "no",
    "security_domain": "none",
    "changes_public_api_contract": "no",
    "changes_persisted_data": "no",
    "irreversible_or_ledger_or_crypto": "no",
    "changes_trust_boundary": "no",
    "blast_radius": "narrow",
    "silent_failure_material_harm": "no",
    "requires_code_understanding": "no",
}


def valid_jev_payload(overrides=None):
    payload = {
        "task_type": "implementation",
        "facts": dict(BASE_FACTS),
        "delegability": 0,
        "evidence": ["added a helper function"],
        "reason": "Single file standalone addition",
    }
    if overrides:
        payload.update(overrides)
    return payload


class JevProviderTests(unittest.TestCase):
    def setUp(self):
        self._env_patcher = mock.patch.dict(os.environ, {}, clear=False)
        self._env_patcher.start()
        self.addCleanup(self._env_patcher.stop)
        for key in (
            jev_provider.JEV_STAGE_ENV,
            jev_provider.JEV_API_KEY_ENV,
            jev_provider.JEV_KILL_SWITCH_ENV,
            jev_provider.JEV_ENDPOINT_ENV,
            jev_provider.JEV_TIMEOUT_ENV,
            jev_provider.JEV_SHADOW_LOG_ENV,
            jev_provider.JEV_SAMPLE_RATE_ENV,
            "JEV_API_KEY",
        ):
            os.environ.pop(key, None)

    def test_kill_switch_detection(self):
        self.assertFalse(jev_provider.is_jev_kill_switch_active())
        for val in ("1", "true", "True", "yes", "YES", "on"):
            with mock.patch.dict(os.environ, {jev_provider.JEV_KILL_SWITCH_ENV: val}):
                self.assertTrue(jev_provider.is_jev_kill_switch_active())
        for val in ("0", "false", "no", "", "off"):
            with mock.patch.dict(os.environ, {jev_provider.JEV_KILL_SWITCH_ENV: val}):
                self.assertFalse(jev_provider.is_jev_kill_switch_active())

    def test_jev_stage_resolution(self):
        self.assertEqual(jev_provider.jev_stage(), "off")
        with mock.patch.dict(os.environ, {jev_provider.JEV_STAGE_ENV: "primary"}):
            self.assertEqual(jev_provider.jev_stage(), "primary")
        with mock.patch.dict(os.environ, {jev_provider.JEV_STAGE_ENV: "shadow"}):
            self.assertEqual(jev_provider.jev_stage(), "shadow")
        # Kill switch forces stage to off
        with mock.patch.dict(
            os.environ,
            {jev_provider.JEV_STAGE_ENV: "primary", jev_provider.JEV_KILL_SWITCH_ENV: "1"},
        ):
            self.assertEqual(jev_provider.jev_stage(), "off")

    def test_missing_api_key_skips_call(self):
        client = mock.Mock()
        result = jev_provider.classify_task_jev("add a helper", client=client)
        self.assertIsNone(result)
        client.assert_not_called()

    def test_kill_switch_active_skips_call(self):
        client = mock.Mock()
        os.environ[jev_provider.JEV_API_KEY_ENV] = "test-key"
        os.environ[jev_provider.JEV_KILL_SWITCH_ENV] = "1"
        result = jev_provider.classify_task_jev("add a helper", client=client)
        self.assertIsNone(result)
        client.assert_not_called()

    def test_successful_classification_with_valid_payload(self):
        payload = valid_jev_payload()
        client = mock.Mock(return_value=payload)
        os.environ[jev_provider.JEV_API_KEY_ENV] = "test-key"

        result = jev_provider.classify_task_jev("add a helper", client=client)
        self.assertIsNotNone(result)
        self.assertEqual(result.source, "jev")
        self.assertEqual(result.task_type, "implementation")
        self.assertEqual(result.level, "L2")  # 1 file touched, result known = L2
        self.assertEqual(result.risk_tier, "standard")
        self.assertEqual(result.unresolved, ())
        client.assert_called_once()

    def test_payload_as_json_string(self):
        payload = valid_jev_payload()
        client = mock.Mock(return_value=json.dumps(payload))
        os.environ[jev_provider.JEV_API_KEY_ENV] = "test-key"

        result = jev_provider.classify_task_jev("add a helper", client=client)
        self.assertIsNotNone(result)
        self.assertEqual(result.source, "jev")

    def test_unknown_facts_are_preserved_without_lookup(self):
        payload = valid_jev_payload()
        payload["facts"]["files_touched"] = "unknown"
        payload["facts"]["changes_security_or_payment_logic"] = "unknown"
        client = mock.Mock(return_value=payload)
        os.environ[jev_provider.JEV_API_KEY_ENV] = "test-key"

        result = jev_provider.classify_task_jev("task with unknowns", client=client)
        self.assertIsNotNone(result)
        self.assertEqual(result.source, "jev")
        self.assertIn("files_touched", result.unresolved)
        self.assertIn("changes_security_or_payment_logic", result.unresolved)
        self.assertEqual(result.facts["files_touched"], "unknown")

    def test_invalid_payload_fails_safely(self):
        os.environ[jev_provider.JEV_API_KEY_ENV] = "test-key"
        # 1. Missing required key
        client = mock.Mock(return_value={"task_type": "implementation"})
        self.assertIsNone(jev_provider.classify_task_jev("task", client=client))

        # 2. Out of domain fact value
        bad_facts = valid_jev_payload()
        bad_facts["facts"]["files_touched"] = "invalid_count"
        client = mock.Mock(return_value=bad_facts)
        self.assertIsNone(jev_provider.classify_task_jev("task", client=client))

        # 3. Invalid JSON string
        client = mock.Mock(return_value="not valid json")
        self.assertIsNone(jev_provider.classify_task_jev("task", client=client))

    def test_timeout_and_network_errors_no_retry(self):
        os.environ[jev_provider.JEV_API_KEY_ENV] = "test-key"
        client = mock.Mock(side_effect=TimeoutError("request timed out"))
        result = jev_provider.classify_task_jev("task", client=client)
        self.assertIsNone(result)
        self.assertEqual(client.call_count, 1)

        client = mock.Mock(side_effect=urllib.error.HTTPError("http://jev", 500, "Internal Server Error", {}, None))
        result = jev_provider.classify_task_jev("task", client=client)
        self.assertIsNone(result)
        self.assertEqual(client.call_count, 1)

    def test_endpoint_host_validation_rejects_subdomain_spoofing(self):
        with self.assertRaises(ValueError):
            jev_provider._default_http_client("task", 1.0, "key", "http://localhost.attacker.example/api")
        with self.assertRaises(ValueError):
            jev_provider._default_http_client("task", 1.0, "key", "http://127.0.0.1.attacker.example/api")
        with self.assertRaises(ValueError):
            jev_provider._default_http_client("task", 1.0, "key", "http://insecure.example.com/api")

    def test_connect_timeout_classified_as_timeout_not_network_error(self):
        os.environ[jev_provider.JEV_API_KEY_ENV] = "test-key"
        client = mock.Mock(side_effect=urllib.error.URLError(socket.timeout("connection timed out")))
        res, failure_kind = jev_provider.classify_task_jev_with_status("task", client=client)
        self.assertIsNone(res)
        self.assertEqual(failure_kind, "timeout")

    def test_response_exceeding_max_bytes_is_rejected(self):
        os.environ[jev_provider.JEV_API_KEY_ENV] = "test-key"
        oversized = "a" * (jev_provider.MAX_RESPONSE_BYTES + 10)
        client = mock.Mock(return_value=oversized)
        res, failure_kind = jev_provider.classify_task_jev_with_status("task", client=client)
        self.assertIsNone(res)
        self.assertEqual(failure_kind, "response_too_large")

    def test_unconfigured_validator_returns_status_without_raising(self):
        os.environ[jev_provider.JEV_API_KEY_ENV] = "test-key"
        client = mock.Mock(return_value=valid_jev_payload())
        with mock.patch.object(jev_provider, "_default_validator", None):
            res, failure_kind = jev_provider.classify_task_jev_with_status("task", client=client, validate_fn=None)
            self.assertIsNone(res)
            self.assertEqual(failure_kind, "validator_not_configured")

    def test_extract_json_payload_picks_last_candidate_across_both_modules(self):
        os.environ[jev_provider.JEV_API_KEY_ENV] = "test-key"
        draft = {"task_type": "review", "facts": {"mechanical_only": "yes"}}
        final = valid_jev_payload()
        two_fences = f"Here is a draft:\n```json\n{json.dumps(draft)}\n```\nHere is the final answer:\n```json\n{json.dumps(final)}\n```"

        from rules import extract_json_payload
        self.assertEqual(extract_json_payload(two_fences), final)
        self.assertEqual(classifier._extract_json_payload(two_fences), final)

        client = mock.Mock(return_value=two_fences)
        res, failure_kind = jev_provider.classify_task_jev_with_status("task", client=client)
        self.assertIsNotNone(res)
        self.assertIsNone(failure_kind)
        self.assertEqual(res.task_type, final["task_type"])

    def test_redirect_handler_raises_http_error(self):
        handler = jev_provider.NoRedirectHandler()
        req = urllib.request.Request("http://localhost:8000")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            handler.redirect_request(req, None, 302, "Found", {}, "http://attacker.com")
        self.assertIn("disallowed", str(ctx.exception))

    def test_daemon_thread_deadline_enforces_wall_clock_timeout_without_blocking(self):
        def slow_fetch(*args, **kwargs):
            time.sleep(2.0)
            return {"task_type": "implementation"}

        with mock.patch("jev_provider._fetch_jev_http", side_effect=slow_fetch):
            t0 = time.perf_counter()
            with self.assertRaises(TimeoutError):
                jev_provider._default_http_client("task", 0.08, "key", "https://example.com")
            elapsed = time.perf_counter() - t0
            self.assertLess(elapsed, 0.35, f"Wall-clock deadline was not enforced: took {elapsed:.3f}s")

    def test_endpoint_host_validation_allows_ipv6_loopback(self):
        # Should not raise ValueError for ::1 or [::1]
        with mock.patch("jev_provider._run_with_daemon_thread_deadline", return_value={"task_type": "implementation"}):
            res = jev_provider._default_http_client("task", 1.0, "key", "http://[::1]:8080/api")
            self.assertEqual(res, {"task_type": "implementation"})

    def test_e2e_real_http_server_redirect_is_blocked(self):
        class RedirectHandler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:9999/leaked")
                self.end_headers()

            def log_message(self, format, *args):
                pass  # suppress stdout logging

        server = http.server.HTTPServer(("127.0.0.1", 0), RedirectHandler)
        port = server.server_port
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()

        try:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                jev_provider._default_http_client("task", 2.0, "secret-key", f"http://127.0.0.1:{port}/classify")
            self.assertEqual(ctx.exception.code, 302)
        finally:
            server.server_close()




class JevChainIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._env_patcher = mock.patch.dict(os.environ, {}, clear=False)
        self._env_patcher.start()
        self.addCleanup(self._env_patcher.stop)
        os.environ[jev_provider.JEV_STAGE_ENV] = "primary"
        os.environ[jev_provider.JEV_API_KEY_ENV] = "test-key"

    def test_classify_task_uses_jev_when_primary_and_successful(self):
        payload = valid_jev_payload()
        with mock.patch("jev_provider.classify_task_jev", return_value=classifier.validate_classifier_output(payload, source="jev")):
            with mock.patch("classifier.classify_task_single") as mock_cli:
                result = classifier.classify_task("add a helper", platform="codex")
                self.assertEqual(result.source, "jev")
                mock_cli.assert_not_called()

    def test_classify_task_falls_through_to_cli_when_jev_fails(self):
        cli_result = classifier.Classification(
            task_type="implementation",
            level="L2",
            risk_flags={flag: False for flag in classifier.RISK_FLAGS},
            reason="cli result",
            source="gpt-5.6-luna",
            facts={name: "no" for name in FACTS},
        )
        with mock.patch("jev_provider.classify_task_jev", return_value=None):
            with mock.patch("classifier.classify_task_single", return_value=cli_result) as mock_cli:
                result = classifier.classify_task("add a helper", platform="codex")
                self.assertEqual(result.source, "gpt-5.6-luna")
                mock_cli.assert_called_once()

    def test_repo_aware_skips_jev(self):
        cli_result = classifier.Classification(
            task_type="implementation",
            level="L2",
            risk_flags={flag: False for flag in classifier.RISK_FLAGS},
            reason="cli result",
            source="gpt-5.6-luna",
            facts={name: "no" for name in FACTS},
        )
        with mock.patch("jev_provider.classify_task_jev") as mock_jev:
            with mock.patch("classifier.classify_task_single", return_value=cli_result):
                result = classifier.classify_task("add a helper", platform="codex", repo_aware=True)
                mock_jev.assert_not_called()
                self.assertEqual(result.source, "gpt-5.6-luna")

    def test_jev_with_unknown_does_not_call_lookup(self):
        payload = valid_jev_payload()
        payload["facts"]["files_touched"] = "unknown"
        jev_classification = classifier.validate_classifier_output(payload, source="jev")

        with mock.patch("jev_provider.classify_task_jev", return_value=jev_classification):
            with mock.patch("classifier.classify_task_single") as mock_cli:
                result = classifier.classify_task("add a helper", platform="codex")
                self.assertEqual(result.source, "jev")
                self.assertIn("files_touched", result.unresolved)
                # Ensure bounded lookup was NOT called
                mock_cli.assert_not_called()


class JevSessionReuseAndKillSwitchTests(unittest.TestCase):
    def test_session_record_includes_origin(self):
        route_result = router.RouteResult(
            platform="codex",
            task_type="implementation",
            base_level="L2",
            level="L2",
            level_name="Medium",
            risk_tier="standard",
            facts={name: "no" for name in FACTS},
            matched_rules=[],
            unresolved=[],
            evidence=[],
            risk_flags={flag: False for flag in router.RISK_FLAGS},
            model="gpt-5.6-luna",
            effort="low",
            mode="single",
            stages=[],
            plan_dir=None,
            rationale=["reason"],
            source="jev",
            execution_strategy="direct",
            orchestration_eligible=False,
        )
        record = router.session_record(route_result, delegability=0)
        self.assertEqual(record.get("origin"), "jev")

    def test_kill_switch_blocks_jev_originated_session_record(self):
        record = {
            "version": 1,
            "saved_at": 1000.0,
            "workspace": route_reuse.workspace_key("/ws"),
            "task_type": "implementation",
            "level": "L2",
            "risk_tier": "standard",
            "risk_flags": {flag: False for flag in router.RISK_FLAGS},
            "facts": {name: "no" for name in FACTS},
            "origin": "jev",
        }
        # Inactive kill switch -> not blocked
        with mock.patch.dict(os.environ, {jev_provider.JEV_KILL_SWITCH_ENV: "0"}):
            blockers = route_reuse.reuse_blockers(record, "/ws", "fix bug", code_change=True, now=1010.0)
            self.assertFalse(any("kill switch" in b for b in blockers))

        # Active kill switch -> blocked!
        with mock.patch.dict(os.environ, {jev_provider.JEV_KILL_SWITCH_ENV: "1"}):
            blockers = route_reuse.reuse_blockers(record, "/ws", "fix bug", code_change=True, now=1010.0)
            self.assertTrue(any("kill switch" in b for b in blockers))

        # Non-jev record -> not blocked even if kill switch is active
        record_non_jev = dict(record, origin="gpt-5.6-luna")
        with mock.patch.dict(os.environ, {jev_provider.JEV_KILL_SWITCH_ENV: "1"}):
            blockers = route_reuse.reuse_blockers(record_non_jev, "/ws", "fix bug", code_change=True, now=1010.0)
            self.assertFalse(any("kill switch" in b for b in blockers))

    def test_reuse_preserves_origin_jev_and_subsequent_reuse_is_blocked_by_kill_switch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "ws"
            workspace.mkdir()
            state_dir = Path(tmpdir) / "state"
            payload = valid_jev_payload()
            jev_res = classifier.validate_classifier_output(payload, source="jev")

            with mock.patch.dict(os.environ, {
                route_reuse.STATE_DIR_ENV: str(state_dir),
                jev_provider.JEV_STAGE_ENV: "primary",
                jev_provider.JEV_API_KEY_ENV: "test-key",
                jev_provider.JEV_KILL_SWITCH_ENV: "0",
            }):
                # 1st run: classifies with Jev
                with mock.patch("jev_provider.classify_task_jev", return_value=jev_res):
                    with mock.patch("os.getcwd", return_value=str(workspace)):
                        code = router.main(["fix parser", "--platform", "codex", "--format", "json", "--session", "sess1"])
                        self.assertEqual(code, 0)

                # Check saved record
                rec = route_reuse.load_record("sess1")
                self.assertIsNotNone(rec)
                self.assertEqual(rec.get("origin"), "jev")
                self.assertEqual(rec.get("reuses", 0), 0)

                # 2nd run: reuses the session
                with mock.patch("os.getcwd", return_value=str(workspace)):
                    code = router.main(["also fix parser whitespace", "--platform", "codex", "--format", "json", "--session", "sess1"])
                    self.assertEqual(code, 0)

                # Check that after 1 reuse, origin is STILL "jev", NOT "reused"!
                rec2 = route_reuse.load_record("sess1")
                self.assertIsNotNone(rec2)
                self.assertEqual(rec2.get("origin"), "jev")
                self.assertEqual(rec2.get("reuses"), 1)

                # 3rd run: NOW kill switch is enabled!
                with mock.patch.dict(os.environ, {jev_provider.JEV_KILL_SWITCH_ENV: "1"}):
                    with mock.patch("os.getcwd", return_value=str(workspace)):
                        # Reuse should be BLOCKED because origin is still "jev"!
                        cl, rec_blocked, why = router.load_reused_classification("sess1", str(workspace), "fix more things", None)
                        self.assertIsNone(cl)
                        self.assertTrue("kill switch" in why)

                # 4th run: Kill switch is turned OFF, but record remains PERMANENTLY invalidated on disk!
                with mock.patch.dict(os.environ, {jev_provider.JEV_KILL_SWITCH_ENV: "0"}):
                    with mock.patch("os.getcwd", return_value=str(workspace)):
                        cl, rec_blocked2, why2 = router.load_reused_classification("sess1", str(workspace), "fix more things", None)
                        self.assertIsNone(cl)
                        self.assertTrue("invalidated" in why2 or "kill switch" in why2)

    def test_sweep_invalidate_jev_records_immediately_blocks_all_sessions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "state"
            with mock.patch.dict(os.environ, {route_reuse.STATE_DIR_ENV: str(state_dir)}):
                # Save 2 Jev records and 1 non-Jev record
                route_reuse.save_record("sess_jev1", "/ws", {"origin": "jev", "task_type": "implementation", "risk_flags": {}})
                route_reuse.save_record("sess_jev2", "/ws", {"origin": "jev", "task_type": "implementation", "risk_flags": {}})
                route_reuse.save_record("sess_other", "/ws", {"origin": "gpt-5.6-luna", "task_type": "implementation", "risk_flags": {}})

                # Immediate sweep
                invalidated = route_reuse.sweep_invalidate_jev_records()
                self.assertEqual(invalidated, 2)

                # Check on disk: both jev records are blocked
                r1 = route_reuse.load_record("sess_jev1")
                self.assertEqual(r1.get("blocked"), "Jev kill switch active")
                r2 = route_reuse.load_record("sess_jev2")
                self.assertEqual(r2.get("blocked"), "Jev kill switch active")

                # Other record is untouched
                r3 = route_reuse.load_record("sess_other")
                self.assertIsNone(r3.get("blocked"))

    def test_sweep_invalidate_does_not_follow_symlinks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "state"
            state_dir.mkdir(mode=0o700)
            outside_target = Path(tmpdir) / "outside.json"
            outside_target.write_text("DO_NOT_OVERWRITE", encoding="utf-8")

            # Plant symlink in state_dir pointing to external target
            symlink_path = state_dir / "session-planted.json"
            symlink_path.symlink_to(outside_target)

            with mock.patch.dict(os.environ, {route_reuse.STATE_DIR_ENV: str(state_dir)}):
                invalidated = route_reuse.sweep_invalidate_jev_records()
                self.assertEqual(invalidated, 0)
                # Ensure symlink target was NOT touched/overwritten
                self.assertEqual(outside_target.read_text(encoding="utf-8"), "DO_NOT_OVERWRITE")
                self.assertTrue(symlink_path.is_symlink())


class JevShadowRunnerTests(unittest.TestCase):
    def test_shadow_runner_non_blocking_returns_immediately(self):
        import time
        primary_payload = valid_jev_payload()
        primary = classifier.validate_classifier_output(primary_payload, source="gpt-5.6-luna")
        # Slow client that would take 5 seconds if run synchronously
        def slow_client(*args, **kwargs):
            time.sleep(5.0)
            return valid_jev_payload()

        with mock.patch.dict(os.environ, {
            jev_provider.JEV_STAGE_ENV: "shadow",
            jev_provider.JEV_API_KEY_ENV: "test-key",
            jev_provider.JEV_SAMPLE_RATE_ENV: "1.0",
        }):
            t0 = time.perf_counter()
            jev_provider.run_shadow_if_enabled("task", primary, client=slow_client, blocking=False)
            elapsed = time.perf_counter() - t0
            self.assertLess(elapsed, 0.1, f"Shadow runner took {elapsed:.3f}s, must be non-blocking (<0.1s)")

    def test_shadow_runner_logs_diff_without_raw_task_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "shadow.jsonl"
            primary_payload = valid_jev_payload()
            primary = classifier.validate_classifier_output(primary_payload, source="gpt-5.6-luna")

            jev_pl = valid_jev_payload()
            jev_pl["facts"]["files_touched"] = "unknown"
            client = mock.Mock(return_value=jev_pl)

            with mock.patch.dict(os.environ, {
                jev_provider.JEV_STAGE_ENV: "shadow",
                jev_provider.JEV_API_KEY_ENV: "test-key",
                jev_provider.JEV_SHADOW_LOG_ENV: str(log_path),
                jev_provider.JEV_SAMPLE_RATE_ENV: "1.0",
            }):
                raw_secret_task = "CONFIDENTIAL_TASK_TEXT_DO_NOT_LOG: add a secret payment handler"
                jev_provider.run_shadow_if_enabled(raw_secret_task, primary, client=client, blocking=True)

            self.assertTrue(log_path.exists())
            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            entry = json.loads(lines[0])
            self.assertEqual(entry["source"], "jev")
            self.assertEqual(entry["primary_source"], "gpt-5.6-luna")
            self.assertIn("diff", entry)
            # Ensure raw task text was NOT logged anywhere
            self.assertNotIn("CONFIDENTIAL_TASK_TEXT_DO_NOT_LOG", lines[0])


class JevUnknownRepromptRegressionTests(unittest.TestCase):
    def setUp(self):
        self._env_patcher = mock.patch.dict(os.environ, {
            jev_provider.JEV_STAGE_ENV: "primary",
            jev_provider.JEV_API_KEY_ENV: "test-key",
        })
        self._env_patcher.start()
        self.addCleanup(self._env_patcher.stop)

    def test_jev_unknown_exits_3_in_non_tty(self):
        payload = valid_jev_payload()
        payload["facts"]["changes_security_or_payment_logic"] = "unknown"
        jev_res = classifier.validate_classifier_output(payload, source="jev")

        with mock.patch("jev_provider.classify_task_jev", return_value=jev_res):
            out = io.StringIO()
            err = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = router.main(["fix auth bug", "--platform", "codex", "--format", "json"])
            self.assertEqual(code, router.EXIT_NEEDS_ANSWER)
            data = json.loads(out.getvalue())
            self.assertEqual(data["unresolved_facts"], ["changes_security_or_payment_logic"])

    def test_jev_unknown_resolved_by_answer_flag(self):
        payload = valid_jev_payload()
        payload["facts"]["changes_security_or_payment_logic"] = "unknown"
        jev_res = classifier.validate_classifier_output(payload, source="jev")

        with mock.patch("jev_provider.classify_task_jev", return_value=jev_res):
            out = io.StringIO()
            err = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = router.main([
                    "fix auth bug", "--platform", "codex", "--format", "json",
                    "--answer", "changes_security_or_payment_logic=yes",
                ])
            self.assertEqual(code, 0)
            data = json.loads(out.getvalue())
            self.assertEqual(data["unresolved_facts"], [])
            self.assertEqual(data["risk_tier"], "elevated")

    def test_jev_unresolved_route_not_saved_to_session(self):
        payload = valid_jev_payload()
        payload["facts"]["changes_security_or_payment_logic"] = "unknown"
        jev_res = classifier.validate_classifier_output(payload, source="jev")

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(os.environ, {route_reuse.STATE_DIR_ENV: str(tmpdir)}):
                with mock.patch("jev_provider.classify_task_jev", return_value=jev_res):
                    with mock.patch("route_reuse.save_record") as mock_save:
                        out = io.StringIO()
                        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                            code = router.main(["fix auth bug", "--platform", "codex", "--format", "json", "--session", "test-sess"])
                        self.assertEqual(code, router.EXIT_NEEDS_ANSWER)
                        mock_save.assert_not_called()


def make_systemone_answers(overrides=None):
    """Build a baseline dictionary of valid answers for all 17 facts."""
    ans = {
        "mechanical_only": {"type": "noul", "noul": 0.05},
        "files_touched": {"type": "choice", "choice": "1", "confidence": 0.95, "probabilities": {"1": 0.95}},
        "crosses_module_boundary": {"type": "noul", "noul": 0.1},
        "crosses_service_boundary": {"type": "noul", "noul": 0.05},
        "fix_or_result_known": {"type": "noul", "noul": 0.95},
        "intermittent_or_concurrency": {"type": "noul", "noul": 0.05},
        "needs_new_structure": {"type": "noul", "noul": 0.05},
        "changes_security_or_payment_logic": {"type": "noul", "noul": 0.05},
        "reviews_security_sensitive_code": {"type": "noul", "noul": 0.05},
        "security_domain": {"type": "choice", "choice": "none", "confidence": 0.95, "probabilities": {"none": 0.95}},
        "changes_public_api_contract": {"type": "noul", "noul": 0.05},
        "changes_persisted_data": {"type": "noul", "noul": 0.05},
        "irreversible_or_ledger_or_crypto": {"type": "noul", "noul": 0.05},
        "changes_trust_boundary": {"type": "noul", "noul": 0.05},
        "blast_radius": {"type": "choice", "choice": "narrow", "confidence": 0.95, "probabilities": {"narrow": 0.95}},
        "silent_failure_material_harm": {"type": "noul", "noul": 0.05},
        "requires_code_understanding": {"type": "noul", "noul": 0.1},
        "task_type": {"type": "choice", "choice": "implementation", "confidence": 0.9, "probabilities": {"implementation": 0.9}},
    }
    if overrides:
        ans.update(overrides)
    return {"model": "jev-latest", "answers": ans, "usage": {"input_tokens": 50, "output_tokens": 10}}


class JevSystemOneIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._env_patcher = mock.patch.dict(os.environ, {
            jev_provider.JEV_STAGE_ENV: "primary",
            jev_provider.JEV_API_KEY_ENV: "test-systemone-key",
            jev_provider.JEV_ENDPOINT_ENV: "https://api.typesafe.ai/v1/systemone",
        })
        self._env_patcher.start()
        self.addCleanup(self._env_patcher.stop)

    def test_build_systemone_request_structure(self):
        req = jev_provider.build_systemone_request("refactor auth token handling", model="custom-jev")
        self.assertEqual(req["model"], "custom-jev")
        self.assertEqual(req["state"], "refactor auth token handling")
        questions = req["questions"]
        self.assertEqual(len(questions), len(rules.FACTS) + 1)
        self.assertEqual(questions["task_type"]["type"], "choice")
        self.assertEqual(set(questions["task_type"]["criteria"]), set(rules.TASK_TYPES))
        self.assertEqual(questions["files_touched"]["type"], "choice")
        self.assertIn("criteria", questions["files_touched"])
        self.assertEqual(questions["security_domain"]["type"], "choice")
        self.assertIn("criteria", questions["security_domain"])
        self.assertEqual(questions["blast_radius"]["type"], "choice")
        self.assertIn("criteria", questions["blast_radius"])
        self.assertEqual(questions["mechanical_only"]["type"], "noul")
        self.assertIn("instructions", questions["mechanical_only"])
        # The live benchmark reports a labelled unknown on a noul fact as unrepresentable rather than
        # scoring it (rules.NOUL_FACTS), so the two sets must agree with what is actually asked here.
        for fact in rules.CHOICE_FACTS:
            self.assertEqual(questions[fact]["type"], "choice", fact)
        for fact in rules.NOUL_FACTS:
            self.assertEqual(questions[fact]["type"], "noul", fact)
        self.assertEqual(set(rules.CHOICE_FACTS) | set(rules.NOUL_FACTS), set(rules.FACTS))

    def test_general_fact_decision_point(self):
        # A general fact reads as yes at or above 0.5 and no below it, with no uncertain band.
        for prob, expected in ((0.50, "yes"), (0.49, "no"), (0.99, "yes"), (0.01, "no")):
            resp = make_systemone_answers({"crosses_module_boundary": {"type": "noul", "noul": prob}})
            parsed = jev_provider.parse_systemone_response(resp, "update feature")
            self.assertEqual(parsed["facts"]["crosses_module_boundary"], expected, f"prob {prob}")

    def test_safety_fact_escalates_on_lighter_evidence(self):
        # A fact whose yes escalates answers yes from 0.4, below the general 0.5 point.
        for prob, expected in ((0.40, "yes"), (0.39, "no")):
            resp = make_systemone_answers({"changes_security_or_payment_logic": {"type": "noul", "noul": prob}})
            parsed = jev_provider.parse_systemone_response(resp, "fix login bug")
            self.assertEqual(parsed["facts"]["changes_security_or_payment_logic"], expected, f"prob {prob}")

    def test_mechanical_only_needs_high_confidence_to_drop_the_floor(self):
        # mechanical_only is the only yes that drops the base below L2, so it takes a high bar.
        for prob, expected, level in ((0.80, "yes", "L1"), (0.79, "no", "L2")):
            resp = make_systemone_answers({"mechanical_only": {"type": "noul", "noul": prob}})
            client = mock.Mock(return_value=resp)
            res, _ = jev_provider.classify_task_jev_with_status("tidy a helper", client=client)
            self.assertEqual(res.facts["mechanical_only"], expected, f"prob {prob}")
            self.assertEqual(res.level, level, f"prob {prob}")

    def test_probability_answers_never_manufacture_an_unknown(self):
        # An unknown blocks the route and asks the user, so it may only come from the model's
        # own "unknown" choice, never from a probability landing mid-scale.
        resp = make_systemone_answers({f: {"type": "noul", "noul": 0.5} for f in rules.FACTS
                                       if rules.FACTS[f] in (rules.YES_NO, rules.YES_NO_UNKNOWN)})
        parsed = jev_provider.parse_systemone_response(resp, "task")
        self.assertEqual([f for f, v in parsed["facts"].items() if v == "unknown"], [])

    def test_strict_yes_no_fact_never_emits_unknown(self):
        # mechanical_only only accepts ('yes', 'no')
        resp = make_systemone_answers({"mechanical_only": {"type": "noul", "noul": 0.5}})
        parsed = jev_provider.parse_systemone_response(resp, "task")
        self.assertIn(parsed["facts"]["mechanical_only"], ("yes", "no"))

    def test_choice_mapping_valid_and_invalid_fallback(self):
        # Valid choice (explicit file evidence keeps the escalating bucket)
        resp = make_systemone_answers({
            "security_domain": {"type": "choice", "choice": "auth", "confidence": 0.9, "probabilities": {"auth": 0.9}},
            "files_touched": {"type": "choice", "choice": "2-5", "confidence": 0.85, "probabilities": {"2-5": 0.85}},
            "blast_radius": {"type": "choice", "choice": "broad", "confidence": 0.8, "probabilities": {"broad": 0.8}},
        })
        parsed = jev_provider.parse_systemone_response(resp, "auth change across 3 files")
        self.assertEqual(parsed["facts"]["security_domain"], "auth")
        self.assertEqual(parsed["facts"]["files_touched"], "2-5")
        self.assertEqual(parsed["facts"]["blast_radius"], "broad")

        # Invalid choice falls back to unknown
        resp = make_systemone_answers({
            "security_domain": {"type": "choice", "choice": "invalid_domain", "confidence": 0.9, "probabilities": {}},
            "files_touched": {"type": "choice", "choice": "100", "confidence": 0.9, "probabilities": {}},
            "blast_radius": {"type": "choice", "choice": "huge", "confidence": 0.9, "probabilities": {}},
        })
        parsed = jev_provider.parse_systemone_response(resp, "task")
        self.assertEqual(parsed["facts"]["security_domain"], "unknown")
        self.assertEqual(parsed["facts"]["files_touched"], "unknown")
        self.assertEqual(parsed["facts"]["blast_radius"], "unknown")

    def test_files_touched_escalating_bucket_without_evidence_forces_unknown(self):
        # A guessed 2-5/6+ on a bare one-line task is a scope inference, not evidence:
        # it must not promote L2 work to L3/L4 on its own.
        for bucket in ("2-5", "6+"):
            resp = make_systemone_answers({
                "files_touched": {"type": "choice", "choice": bucket, "confidence": 0.9, "probabilities": {bucket: 0.9}},
            })
            parsed = jev_provider.parse_systemone_response(resp, "Implement user profile avatar upload")
            self.assertEqual(parsed["facts"]["files_touched"], "unknown", f"bucket {bucket}")
            self.assertIn("forced to unknown", parsed["reason"])
        # Explicit evidence keeps the bucket: a stated count or a named path.
        for task in ("auth change across 3 files", "Fix pagination in view.py and api.py", "Update logger calls across 15 files"):
            resp = make_systemone_answers({
                "files_touched": {"type": "choice", "choice": "2-5", "confidence": 0.9, "probabilities": {"2-5": 0.9}},
            })
            parsed = jev_provider.parse_systemone_response(resp, task)
            self.assertEqual(parsed["facts"]["files_touched"], "2-5", f"task {task!r}")
        # A bare "1" is routing-neutral and stays: forcing it unknown would only block an executable L2.
        resp = make_systemone_answers({
            "files_touched": {"type": "choice", "choice": "1", "confidence": 0.9, "probabilities": {"1": 0.9}},
        })
        parsed = jev_provider.parse_systemone_response(resp, "Fix a helper")
        self.assertEqual(parsed["facts"]["files_touched"], "1")
        # Invariant: the guard policy in enforce_files_touched_contract explicitly assumes
        # files_touched='1' is routing-neutral and never appears as an escalating condition in DIFFICULTY_RULES.
        for rule_level, name, cond in rules.DIFFICULTY_RULES:
            if "files_touched" in cond:
                self.assertNotIn(
                    "1", cond["files_touched"],
                    f"DIFFICULTY_RULES {rule_level}:{name} conditions on files_touched='1'; guard assumption violated",
                )

    def test_17_facts_and_5_field_contract_passes_validation(self):
        resp = make_systemone_answers({
            "changes_public_api_contract": {"type": "noul", "noul": 0.95},
        })
        client = mock.Mock(return_value=resp)
        result, failure_kind = jev_provider.classify_task_jev_with_status("update public API", client=client)
        self.assertIsNone(failure_kind)
        self.assertIsNotNone(result)
        self.assertEqual(result.source, "jev")
        self.assertEqual(result.facts["changes_public_api_contract"], "yes")
        self.assertEqual(result.level, "L4")
        self.assertTrue(result.risk_flags["public_api_change"])
        self.assertIsInstance(result.reason, str)
        self.assertTrue(len(result.reason) > 0)
        self.assertIsInstance(result.evidence, tuple)
        self.assertIn(result.delegability, (0, 1, 2))

    def test_malformed_systemone_response_fails_safely_to_fallback(self):
        # Missing answers
        client = mock.Mock(return_value={"model": "jev-latest"})
        res, failure_kind = jev_provider.classify_task_jev_with_status("task", client=client)
        self.assertIsNone(res)
        self.assertEqual(failure_kind, "invalid_json")

        # Missing one fact
        incomplete = make_systemone_answers()
        del incomplete["answers"]["mechanical_only"]
        client = mock.Mock(return_value=incomplete)
        res, failure_kind = jev_provider.classify_task_jev_with_status("task", client=client)
        self.assertIsNone(res)
        self.assertEqual(failure_kind, "invalid_json")

        # Non-numeric noul
        bad_noul = make_systemone_answers({"mechanical_only": {"type": "noul", "noul": "not-a-number"}})
        client = mock.Mock(return_value=bad_noul)
        res, failure_kind = jev_provider.classify_task_jev_with_status("task", client=client)
        self.assertIsNone(res)
        self.assertEqual(failure_kind, "invalid_json")

    def test_task_type_comes_from_jev_answer_not_task_keywords(self):
        # A task whose text merely contains "review" is still the implementation Jev reported.
        resp = make_systemone_answers()
        client = mock.Mock(return_value=resp)
        res, _ = jev_provider.classify_task_jev_with_status("Fix the pagination bug in the code review tool", client=client)
        self.assertEqual(res.task_type, "implementation")

        # Jev's own read-only answer is honoured.
        resp = make_systemone_answers({
            "files_touched": {"type": "choice", "choice": "0", "confidence": 0.99, "probabilities": {"0": 0.99}},
            "task_type": {"type": "choice", "choice": "review", "confidence": 0.95, "probabilities": {"review": 0.95}},
        })
        client = mock.Mock(return_value=resp)
        res, _ = jev_provider.classify_task_jev_with_status("audit authentication code for vulnerabilities", client=client)
        self.assertEqual(res.task_type, "review")
        self.assertEqual(res.facts["files_touched"], "0")

    def test_unreadable_task_type_never_routes_to_a_read_only_type(self):
        for answer in ({"type": "choice", "choice": "not-a-task-type", "confidence": 0.9, "probabilities": {}},
                       {"type": "noul", "noul": 0.9}):
            resp = make_systemone_answers({"task_type": answer})
            client = mock.Mock(return_value=resp)
            res, _ = jev_provider.classify_task_jev_with_status("review the login page copy", client=client)
            self.assertEqual(res.task_type, "implementation")

    def test_zero_files_with_a_code_change_type_drops_the_scope_claim(self):
        resp = make_systemone_answers({
            "files_touched": {"type": "choice", "choice": "0", "confidence": 0.9, "probabilities": {"0": 0.9}},
        })
        client = mock.Mock(return_value=resp)
        res, failure_kind = jev_provider.classify_task_jev_with_status("add a helper", client=client)
        self.assertIsNone(failure_kind)
        self.assertEqual(res.task_type, "implementation")
        self.assertEqual(res.facts["files_touched"], "unknown")

    def test_delegability_from_facts(self):
        resp = make_systemone_answers({
            "changes_security_or_payment_logic": {"type": "noul", "noul": 0.95},
        })
        client = mock.Mock(return_value=resp)
        res, _ = jev_provider.classify_task_jev_with_status("update payment gateway logic", client=client)
        self.assertIsNotNone(res)
        self.assertEqual(res.delegability, 0)


if __name__ == "__main__":
    unittest.main()

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pipeline  # noqa: E402
import route_reuse  # noqa: E402
import router  # noqa: E402


def classification(task_type="implementation", level="L3", tier="standard", flags=()):
    return router.Classification(
        task_type=task_type, level=level, risk_flags={f: f in flags for f in router.RISK_FLAGS},
        reason="classified", source="primary", facts={"files_touched": "1"}, matched_rules=("rule",), risk_tier=tier,
    )


class ReuseCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name) / "state"
        self.workspace = Path(self._tmp.name) / "ws"
        self.workspace.mkdir()
        env = mock.patch.dict(os.environ, {route_reuse.STATE_DIR_ENV: str(self.state)})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.workspace)
        os.environ.pop(route_reuse.SESSION_ENV, None)

    def route(self, task, *extra, classified=None, session="s1"):
        """Run router.main for a task; returns (payload, number of classifier calls)."""
        calls = []

        def fake(*_args, **_kwargs):
            calls.append(1)
            return classified or classification()

        args = [task, "--platform", "codex", "--format", "json", *(["--session", session] if session else []), *extra]
        out = io.StringIO()
        with mock.patch.object(router, "classify_task", fake), contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = router.main(args)
        self.assertEqual(rc, 0)
        return json.loads(out.getvalue()), len(calls)


class RouteReuseTests(ReuseCase):
    def test_a_follow_up_reuses_the_stored_route_without_calling_the_classifier(self):
        first, first_calls = self.route("fix the parser bug")
        second, second_calls = self.route("also handle empty input")
        self.assertEqual((first_calls, second_calls), (1, 0))
        self.assertTrue(second["reuse"]["reused"])
        self.assertEqual((second["task_type"], second["effective_level"], second["risk_tier"]), (first["task_type"], first["effective_level"], first["risk_tier"]))
        self.assertEqual(second["source"], "reused")
        self.assertEqual([s["model"] for s in second["steps"]], [s["model"] for s in first["steps"]])
        self.assertIn("also handle empty input", second["pipeline"]["task"])

    def test_reuse_keeps_the_stored_risk_flags_tier_and_scope_guard(self):
        risky = classification(level="L4", tier="elevated", flags=("security_sensitive",))
        first, _ = self.route("harden the session handling", classified=risky)
        second, calls = self.route("also cover the second endpoint")
        self.assertEqual(calls, 0)
        self.assertEqual(second["risk_tier"], "elevated")
        self.assertEqual(second["risk_flags"], first["risk_flags"])
        self.assertIn("scope_guard", second)

    def test_no_session_means_no_reuse_and_nothing_is_stored(self):
        self.route("fix the parser bug", session=None)
        _, calls = self.route("also handle empty input", session=None)
        self.assertEqual(calls, 1)
        self.assertFalse(self.state.exists())

    def test_the_session_can_come_from_the_environment(self):
        os.environ[route_reuse.SESSION_ENV] = "env-session"
        self.route("fix the parser bug", session=None)
        _, calls = self.route("also handle empty input", session=None)
        self.assertEqual(calls, 0)

    def test_sessions_do_not_share_routes(self):
        self.route("fix the parser bug", session="a")
        _, calls = self.route("also handle empty input", session="b")
        self.assertEqual(calls, 1)

    def test_each_blocker_forces_a_new_classification(self):
        cases = {
            "operation change": "explain why the parser fails",
            "mixed operation": "check the parser and fix the bug",
            "scope growth": "rename it across all the modules",
            "new risk evidence": "update the login token refresh",
            "korean risk": "결제 로직도 수정해줘",
        }
        for name, task in cases.items():
            with self.subTest(name=name):
                self.route("fix the parser bug")
                payload, calls = self.route(task)
                self.assertEqual(calls, 1, task)
                self.assertFalse(payload["reuse"]["reused"])
                self.assertTrue(payload["reuse"]["reason"])

    def test_a_task_that_names_no_operation_still_reuses(self):
        self.route("fix the parser bug")
        _, calls = self.route("the second file too")
        self.assertEqual(calls, 0)

    def test_already_raised_routes_reuse_even_with_risk_words(self):
        self.route("harden auth", classified=classification(level="L4", tier="elevated", flags=("authentication",)))
        _, calls = self.route("fix the token expiry too")
        self.assertEqual(calls, 0)

    def test_a_different_workspace_reclassifies(self):
        self.route("fix the parser bug")
        other = Path(self._tmp.name) / "other"
        other.mkdir()
        os.chdir(other)
        payload, calls = self.route("also handle empty input")
        self.assertEqual(calls, 1)
        self.assertIn("workspace changed", payload["reuse"]["reason"])

    def test_an_expired_route_reclassifies(self):
        self.route("fix the parser bug")
        later = route_reuse.time.time() + route_reuse.REUSE_TTL_SECONDS + 60
        with mock.patch.object(route_reuse.time, "time", return_value=later):
            payload, calls = self.route("also handle empty input")
        self.assertEqual(calls, 1)
        self.assertIn("expired", payload["reuse"]["reason"])

    def test_the_ttl_is_not_extended_by_reuse(self):
        self.route("fix the parser bug")
        saved = route_reuse.load_record("s1")["saved_at"]
        self.route("also handle empty input")
        record = route_reuse.load_record("s1")
        self.assertEqual((record["saved_at"], record["reuses"]), (saved, 1))

    def test_no_reuse_flag_and_explicit_pins_bypass_the_store(self):
        self.route("fix the parser bug")
        _, calls = self.route("also handle empty input", "--no-reuse")
        self.assertEqual(calls, 1)
        payload, calls = self.route("also handle empty input", "--level", "L2", "--task-type", "implementation")
        self.assertEqual((calls, payload["source"]), (0, "manual"))
        self.assertFalse(payload["reuse"]["reused"])

    def test_a_fallback_classification_is_never_stored(self):
        fallback = router.fallback_classification("classifier down")
        with mock.patch.object(router, "classify_task", lambda *a, **k: fallback), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                mock.patch("sys.stdin.isatty", return_value=False):
            router.main(["fix it", "--platform", "codex", "--format", "json", "--session", "s1", "--no-prompt"])
        self.assertIsNone(route_reuse.load_record("s1"))

    def test_a_corrupt_or_tampered_record_reclassifies_instead_of_crashing(self):
        self.route("fix the parser bug")
        path = route_reuse.record_path("s1")
        path.write_text("{not json", encoding="utf-8")
        _, calls = self.route("also handle empty input")
        self.assertEqual(calls, 1)
        record = route_reuse.load_record("s1")
        record["level"] = "L9"
        path.write_text(json.dumps(record), encoding="utf-8")
        payload, calls = self.route("and another one")
        self.assertEqual(calls, 1)
        self.assertIn("invalid", payload["reuse"]["reason"])

    def test_route_file_replay_rejects_session_options(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            router.parse_args(["--route-file", "r.json", "--session", "s"])


class ReviewHardeningTests(ReuseCase):
    def test_a_migration_flag_does_not_cover_a_later_security_change(self):
        self.route("add the orders table migration", classified=classification(level="L4", flags=("data_migration",)))
        payload, calls = self.route("add the payment refund endpoint and rotate the auth secret")
        self.assertEqual(calls, 1)
        self.assertIn("security", payload["reuse"]["reason"])

    def test_a_critical_tier_without_security_flags_does_not_cover_security_words(self):
        self.route("purge the ledger", classified=classification(level="L5", tier="critical"))
        payload, calls = self.route("fix the token refresh")
        self.assertEqual(calls, 1)
        self.assertIn("security", payload["reuse"]["reason"])

    def test_common_security_vocabulary_forces_reclassification(self):
        for task in ("fix the SQL injection in the search filter", "add a JWT refresh endpoint", "wire up stripe", "harden the csrf check",
                     "세션 만료 수정", "관리자 권한 수정", "cors headers"):
            with self.subTest(task=task):
                self.route("fix the parser bug")
                _, calls = self.route(task)
                self.assertEqual(calls, 1)

    def test_a_read_only_route_is_not_reused_for_a_modification(self):
        review = classification(task_type="review", level="L3")
        for follow_up in ("이 부분 고쳐줘", "리팩토링 해줘", "the second file too"):
            with self.subTest(follow_up=follow_up):
                self.route("review the parser", classified=review)
                _, calls = self.route(follow_up)
                self.assertEqual(calls, 1)

    def test_a_different_pinned_task_type_reclassifies(self):
        self.route("review the parser", classified=classification(task_type="review"))
        _, calls = self.route("look at it again", "--task-type", "implementation")
        self.assertEqual(calls, 1)

    def test_malformed_records_reclassify_instead_of_crashing(self):
        for field, value in (("saved_at", "soon"), ("risk_flags", ["security_sensitive"]), ("delegability", 99), ("reuses", "x"), ("facts", [])):
            with self.subTest(field=field):
                self.route("fix the parser bug")
                record = route_reuse.load_record("s1")
                record[field] = value
                route_reuse.record_path("s1").write_text(json.dumps(record), encoding="utf-8")
                payload, calls = self.route("also handle empty input")
                self.assertEqual(calls, 1)
                self.assertFalse(payload["reuse"]["reused"])

    def test_a_future_timestamp_does_not_live_forever(self):
        self.route("fix the parser bug")
        record = route_reuse.load_record("s1")
        record["saved_at"] = 9e15
        route_reuse.record_path("s1").write_text(json.dumps(record), encoding="utf-8")
        _, calls = self.route("also handle empty input")
        self.assertEqual(calls, 1)

    def test_the_record_is_private_atomic_and_never_follows_a_symlink(self):
        self.route("fix the parser bug")
        path = route_reuse.record_path("s1")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual([p.name for p in path.parent.iterdir()], [path.name])
        target = self.workspace / "victim.txt"
        target.write_text("keep")
        path.unlink()
        path.symlink_to(target)
        self.assertIsNone(route_reuse.load_record("s1"))
        self.route("fix the parser bug")
        self.assertEqual(target.read_text(), "keep")
        self.assertFalse(path.is_symlink())

    def test_foreign_or_oversized_records_are_ignored(self):
        self.route("fix the parser bug")
        with mock.patch.object(route_reuse.os, "geteuid", return_value=os.geteuid() + 1):
            self.assertIsNone(route_reuse.load_record("s1"))
        route_reuse.record_path("s1").write_text(" " * (route_reuse.MAX_RECORD_BYTES + 1), encoding="utf-8")
        self.assertIsNone(route_reuse.load_record("s1"))

    def test_needs_context_and_evidence_survive_reuse_via_a_blocker(self):
        uncertain = router.Classification(**{**classification().__dict__, "needs_context": True, "evidence": ("a.py",)})
        self.route("fix the parser bug", classified=uncertain)
        payload, calls = self.route("also handle empty input")
        self.assertEqual(calls, 1)
        self.assertIn("context", payload["reuse"]["reason"])

    def test_evidence_is_kept_on_a_reused_route(self):
        evidence = router.Classification(**{**classification().__dict__, "evidence": ("a.py",)})
        self.route("fix the parser bug", classified=evidence)
        payload, calls = self.route("also handle empty input")
        self.assertEqual((calls, payload["evidence"]), (0, ["a.py"]))

    def test_a_reuse_chain_is_capped(self):
        self.route("fix the parser bug")
        for _ in range(route_reuse.MAX_REUSES):
            _, calls = self.route("also the next file")
            self.assertEqual(calls, 0)
        payload, calls = self.route("also the next file")
        self.assertEqual(calls, 1)
        self.assertIn("times already", payload["reuse"]["reason"])

    def test_a_non_mapping_reuse_field_is_a_validation_error_not_a_crash(self):
        payload, _ = self.route("fix the parser bug")
        payload["reuse"] = "s1"
        with self.assertRaises(ValueError):
            pipeline.Pipeline.validate(payload)

    def test_a_route_file_cannot_invalidate_another_sessions_record(self):
        payload, _ = self.route("fix the parser bug", session="mine")
        payload["reuse"]["session"] = "mine"
        payload["pipeline"]["review"] = payload["pipeline"]["replan"] = None
        fake = self.state.parent / "bin"
        fake.mkdir()
        exe = fake / "codex"
        exe.write_text(f"#!{sys.executable}\nimport sys\nsys.exit(7)\n", encoding="utf-8")
        exe.chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": f"{fake}{os.pathsep}{os.environ['PATH']}"}), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            pipeline.run_route(payload, [], str(self.workspace), own_session="someone-else")
        self.assertIsNone(route_reuse.load_record("mine")["blocked"])


class OutcomeTests(ReuseCase):
    def test_a_run_that_replanned_or_failed_invalidates_the_stored_route(self):
        for replans, code, expected in ((0, 0, None), (1, 0, "re-planned"), (0, 10, "exit 10")):
            with self.subTest(replans=replans, code=code):
                self.route("fix the parser bug")
                route_reuse.mark_outcome("s1", replans, code)
                self.assertEqual(route_reuse.load_record("s1")["blocked"], expected)
                payload, calls = self.route("also handle empty input")
                self.assertEqual(calls, 0 if expected is None else 1)

    def test_the_pipeline_records_the_outcome_for_its_session(self):
        payload, _ = self.route("fix the parser bug")
        payload["pipeline"]["review"] = payload["pipeline"]["replan"] = None
        fake = self.state.parent / "bin"
        fake.mkdir()
        exe = fake / "codex"
        exe.write_text(f"#!{sys.executable}\nimport sys\nsys.exit(7)\n", encoding="utf-8")
        exe.chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": f"{fake}{os.pathsep}{os.environ['PATH']}"}), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = pipeline.run_route(payload, [], str(self.workspace), own_session="s1")
        self.assertEqual(rc, 7)
        self.assertEqual(route_reuse.load_record("s1")["blocked"], "exit 7")


if __name__ == "__main__":
    unittest.main()

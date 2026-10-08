import json
import sys
import unittest

from tests.hook_helpers import HookCase, run_script

PY = json.dumps(sys.executable)


class GateCliTest(HookCase):
    def gate(self, *args):
        argv = ["--cwd", str(self.repo), *args]
        return run_script("bin/mer-gate", env=self.env(), argv=argv, cwd=str(self.root))

    def cfg(self, **checks):
        self.write_repo_config({"difficulty": {"backend": "fake"}, "gate": {"checks": checks}})

    def test_no_checks_are_not_run_never_passed(self):
        p = self.gate()
        out = json.loads(p.stdout)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(
            {k: v["status"] for k, v in out["checks"].items()},
            {"test": "not_run", "lint": "not_run", "typecheck": "not_run", "build": "not_run"},
        )
        self.assertEqual(out["overall"], "incomplete")

    def test_pass_fail_and_not_run_mix(self):
        self.cfg(test=f"{PY} -c \"print('ok')\"", lint=f"{PY} -c \"import sys; print('bad'); sys.exit(3)\"")
        out = json.loads(self.gate().stdout)
        self.assertEqual(out["checks"]["test"]["status"], "passed")
        self.assertIn("ok", out["checks"]["test"]["output_tail"])
        self.assertEqual(out["checks"]["lint"]["status"], "failed")
        self.assertEqual(out["checks"]["lint"]["exit_code"], 3)
        self.assertEqual(out["checks"]["typecheck"]["status"], "not_run")
        self.assertEqual(out["overall"], "failed")

    def test_all_found_and_passing_is_passed(self):
        ok = f"{PY} -c pass"
        self.cfg(test=ok, lint=ok, typecheck=ok, build=ok)
        self.assertEqual(json.loads(self.gate().stdout)["overall"], "passed")

    def test_timeout_is_failed(self):
        self.cfg(test=f'{PY} -c "import time; time.sleep(30)"')
        out = json.loads(self.gate("--timeout", "1").stdout)
        self.assertEqual(out["checks"]["test"]["status"], "failed")
        self.assertIn("timeout", out["checks"]["test"]["reason"])

    def test_unrunnable_command_is_failed_not_crash(self):
        (self.repo / "AGENTS.md").write_text("`pytest-does-not-exist-xyz`\n`npm test`")
        self.write_repo_config({"gate": {"checks": {"lint": "definitely-not-a-binary-xyz"}}})
        out = json.loads(self.gate().stdout)
        self.assertEqual(out["checks"]["lint"]["status"], "failed")

    def test_session_flags_are_gone(self):
        for flag in (["--session", "x"], ["--mark", "plan", "done"], ["--review", "approved"]):
            self.assertNotEqual(self.gate(*flag).returncode, 0)

    def test_bad_gate_config_reports_error_exit_nonzero(self):
        self.write_repo_config({"gate": {"checks": {"tset": "x"}}})
        p = self.gate()
        self.assertNotEqual(p.returncode, 0)
        out = json.loads(p.stdout)
        self.assertEqual(out["overall"], "failed")
        self.assertIn("tset", out["error"])
        self.assertNotIn("Traceback", p.stderr)

    def test_broken_json_config_reports_json_error(self):
        (self.repo / ".model-effort-router.json").write_text("{nope")
        p = self.gate()
        self.assertEqual(json.loads(p.stdout)["overall"], "failed")

    def test_user_config_gate_checks_honored_repo_wins_per_kind(self):
        ucfg = self.home / "u.json"
        ucfg.write_text(json.dumps({"gate": {"checks": {"test": f"{PY} -c pass", "lint": f"{PY} -c pass"}}}))
        self.write_repo_config({"gate": {"checks": {"lint": f"{PY} -c 'import sys; sys.exit(1)'"}}})
        p = run_script(
            "bin/mer-gate", env=self.env(MER_USER_CONFIG=str(ucfg)), argv=["--cwd", str(self.repo)], cwd=str(self.root)
        )
        out = json.loads(p.stdout)["checks"]
        self.assertEqual(out["test"]["status"], "passed")
        self.assertEqual(out["lint"]["status"], "failed")

    def test_grandchild_killed_after_normal_exit(self):
        marker = self.root / "alive.txt"
        script = f"import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(2); open({str(marker)!r},'w').write('x')'])"
        self.cfg(test=f'{PY} -c "{script}"')
        self.gate()
        import time

        time.sleep(3)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.hook_helpers import ROOT

PLUGIN = ROOT / 'plugins' / 'antigravity-model-effort-router'


class AntigravityBundleTest(unittest.TestCase):
    def test_native_manifest_validates(self):
        manifest = json.loads((PLUGIN / 'plugin.json').read_text())
        self.assertEqual(set(manifest), {'$schema', 'name', 'description'})
        self.assertEqual(manifest['name'], 'model-effort-router')
        checked = subprocess.run(['agy', 'plugin', 'validate', str(PLUGIN)], capture_output=True, text=True, timeout=30)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)

    def test_real_bundle_wrapper_dispatches_routed_manual_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            fake = root / 'fake-bin'
            fake.mkdir()
            record = root / 'agy.json'
            agy = fake / 'agy'
            agy.write_text('#!/usr/bin/env python3\nimport json, os, sys\n'
                           'open(os.environ["RECORD"],"w").write(json.dumps({"argv":sys.argv,"cwd":os.getcwd(),"host":os.getenv("MER_HOST"),"guard":os.getenv("MER_CLASSIFIER")}))\n')
            agy.chmod(0o755)
            (root / '.model-effort-router.json').write_text('{"router":{"mode":"manual"}}')
            env = {k: v for k, v in os.environ.items() if not k.startswith('MER_')}
            env.update(PATH=str(fake) + os.pathsep + os.environ['PATH'], HOME=str(root), MER_HOST='codex', RECORD=str(record))
            result = subprocess.run([sys.executable, str(PLUGIN / 'bin' / 'mer'), 'chat', '--cwd', str(root),
                                     '/router session=balanced:medium\nFix parser.py'],
                                    capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            captured = json.loads(record.read_text())
            self.assertEqual(captured['argv'][1:], ['--model', 'claude-sonnet-5-5-medium', '--effort', 'medium',
                                                   '--prompt-interactive', 'Fix parser.py'])
            self.assertTrue(captured['argv'][0].endswith('/agy'))
            self.assertEqual((captured['cwd'], captured['host'], captured['guard']), (str(root), 'antigravity', '1'))

    def test_explicit_host_override_and_run_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            p = subprocess.run([sys.executable, str(PLUGIN / 'bin' / 'mer'), 'run', '--host', 'codex', '--dry-run',
                                '--level', 'L2', '--cwd', str(root), 'Fix parser.py'],
                               capture_output=True, text=True, timeout=30,
                               env={**os.environ, 'HOME': str(root), 'MER_STATE_DIR': str(root / 'state')})
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn('host: codex', p.stdout)
            p = subprocess.run([sys.executable, str(PLUGIN / 'bin' / 'mer'), 'run', '--cwd', str(root), 'Fix parser.py'],
                               capture_output=True, text=True, timeout=30,
                               env={**os.environ, 'HOME': str(root), 'MER_STATE_DIR': str(root / 'state')})
            self.assertEqual(p.returncode, 2)
            self.assertIn('read-only and resume contracts are unverified', p.stderr)

    def test_bundle_has_native_skill_and_no_unsafe_hook(self):
        skill = (PLUGIN / 'skills' / 'model-effort-router' / 'SKILL.md').read_text()
        self.assertIn('mer chat', skill)
        self.assertIn('subscription', skill)
        self.assertFalse((PLUGIN / 'hooks.json').exists())
        self.assertTrue(os.access(PLUGIN / 'bin' / 'mer', os.X_OK))


if __name__ == '__main__':
    unittest.main()

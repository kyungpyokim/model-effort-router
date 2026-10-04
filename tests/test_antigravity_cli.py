import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from model_effort_router import cli
from model_effort_router.difficulty.decision import DifficultyInput
from model_effort_router.difficulty.subscription import SubscriptionBackend


class AntigravityChatTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.env = {'HOME': str(self.root), 'MER_HOST': 'antigravity',
                    'MER_STATE_DIR': str(self.root / 'state'), 'PATH': os.environ['PATH']}
        self.config = self.root / '.model-effort-router.json'
        self.calls = []
        previous = os.getcwd()
        self.addCleanup(os.chdir, previous)

    def invoke(self, text, *flags, command='chat'):
        out, err = io.StringIO(), io.StringIO()
        def execute(file, argv, env):
            self.calls.append((file, argv, env, os.getcwd()))
        with mock.patch('sys.stderr', err):
            rc = cli.main([command, '--cwd', str(self.root), *flags, text], env=self.env,
                          out=out, exec_fn=execute)
        return rc, out.getvalue(), err.getvalue()

    def test_manual_real_dispatch_and_guard(self):
        self.config.write_text('{"router":{"mode":"manual"}}')
        rc, _, _ = self.invoke('/router session=balanced:medium\nFix parser.py')
        self.assertEqual(rc, 0)
        file, argv, env, cwd = self.calls[0]
        self.assertEqual((file, argv, cwd), ('agy', ['agy', '--model', 'claude-sonnet-5-5-medium',
                          '--effort', 'medium', '--prompt-interactive', 'Fix parser.py'], str(self.root)))
        self.assertEqual(env['MER_CLASSIFIER'], '1')
        self.assertEqual(env['MER_HOST'], 'antigravity')

    def test_off_and_manual_without_profile_start_defaults_without_classifier(self):
        for config, request in (({}, '/router off\nFix parser.py'),
                                ({'router': {'mode': 'manual'}}, 'Fix parser.py')):
            self.config.write_text(json.dumps(config))
            with mock.patch.object(SubscriptionBackend, 'classify', side_effect=AssertionError('called')) as classify:
                self.assertEqual(self.invoke(request)[0], 0)
            classify.assert_not_called()
            self.assertEqual(self.calls[-1][1], ['agy', '--prompt-interactive', 'Fix parser.py'])

    def test_run_rejected_before_configuration_and_classifier(self):
        self.config.write_text('bad json')
        with mock.patch.object(cli, 'load_configs', side_effect=AssertionError('loaded')) as load:
            rc, _, error = self.invoke('Fix parser.py', command='run')
        self.assertEqual(rc, 2)
        self.assertIn('not supported', error)
        load.assert_not_called()
        self.assertEqual(self.calls, [])

    def test_subscription_primary_or_fallback_refused_before_model_call(self):
        for config in ({}, {'difficulty': {'backend': 'jev', 'fallback': 'subscription'}}):
            self.config.write_text(json.dumps(config))
            with mock.patch.object(SubscriptionBackend, 'classify', side_effect=AssertionError('called')) as classify:
                rc, _, error = self.invoke('Fix parser.py')
            self.assertEqual(rc, 2)
            self.assertIn('subscription', error)
            classify.assert_not_called()
        self.assertEqual(self.calls, [])

    def test_offline_dry_run_keeps_requested_xhigh_and_no_run_review_hint(self):
        rc, out, error = self.invoke('Fix auth.py', '--dry-run', '--level', 'L5')
        self.assertEqual(rc, 0)
        self.assertIn('claude-opus-5-5-high', out)
        self.assertIn('requested xhigh', error)
        self.assertNotIn('mer run', error)
        self.assertIn('cwd: ' + str(self.root), out)
        self.assertEqual(self.calls, [])

    def test_plan_and_review_rejected_without_readonly_claim(self):
        for request in ('plan only: add cache to parser.py', 'review only: check parser.py'):
            rc, _, error = self.invoke(request, '--dry-run', '--level', 'L2')
            self.assertEqual(rc, 2)
            self.assertIn('read-only', error)
        self.assertEqual(self.calls, [])

    def test_missing_agy_has_clear_failure(self):
        self.config.write_text('{"router":{"mode":"manual"}}')
        with mock.patch.object(cli.os, 'execvpe', side_effect=FileNotFoundError('agy')):
            # Explicit injection: main's default function is bound at import time.
            with mock.patch('sys.stderr', io.StringIO()):
                rc = cli.main(['chat', '--cwd', str(self.root), '/router session=economy:medium\nFix parser.py'],
                              env=self.env, exec_fn=cli.os.execvpe)
        self.assertEqual(rc, 127)

    def test_subscription_backend_itself_never_falls_through_to_codex(self):
        runner = mock.Mock(side_effect=AssertionError('spawned'))
        with self.assertRaisesRegex(ValueError, 'antigravity'):
            SubscriptionBackend(host='antigravity', runner=runner).classify(DifficultyInput(task='Fix parser.py'), 1)
        runner.assert_not_called()

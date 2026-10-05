import unittest
from model_effort_router.policy.config import resolve_config
from model_effort_router.policy.overrides import parse_override

class RoleOverrideTests(unittest.TestCase):
    def test_role_effort_override_and_mode(self):
        o, rest=parse_override("/router role=review effort=high\ninspect diff")
        self.assertEqual((o.role,o.effort,rest),("review","high","inspect diff"))
        self.assertEqual(parse_override("/router off")[0].mode,"off")
    def test_legacy_session_override_is_actionable_rejection(self):
        self.assertTrue(parse_override("/router session=frontier:high")[0].rejected)
    def test_non_command_is_preserved(self):
        text="see /router off in the docs"
        self.assertEqual(parse_override(text)[1],text)

class ConfigPrecedenceTest(unittest.TestCase):
    def test_role_model_defaults_and_repo_precedence(self):
        c=resolve_config(user={"router":{"mode":"off"}},repo={"router":{"mode":"auto"}})
        self.assertEqual(c.mode,"auto")
        self.assertEqual(c.models["codex"]["execution"]["primary"],"gpt-6-luna")
        self.assertEqual(c.models["codex"]["reasoning"]["primary"],"gpt-6.1-sol")
    def test_custom_primary_fallback_effort(self):
        c=resolve_config(repo={"models":{"codex":{"execution":{"primary":"custom","fallback":"backup","efforts":["medium","high"]}}}})
        self.assertEqual((c.models["codex"]["execution"]["primary"],c.models["codex"]["execution"]["fallback"]),("custom","backup"))
    def test_legacy_policy_settings_fail_with_migration_message(self):
        for value, match in (({"session":{"default":"frontier"}},"session/profile"),
                             ({"difficulty":{"backend":"nimble_jev"}},"nimble_jev.*removed")):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,match):
                resolve_config(repo=value)
    def test_config_inputs_are_not_mutated_and_timeout_is_validated(self):
        src={"router":{"mode":"off"}}
        resolve_config(repo=src)
        self.assertEqual(src,{"router":{"mode":"off"}})
        with self.assertRaises(ValueError):
            resolve_config(repo={"difficulty":{"timeout_s":float("nan")}})

    def test_standalone_gate_configuration_remains_accepted_by_router(self):
        cfg = resolve_config(repo={"gate": {"checks": {"test": "python -m unittest"}}})
        self.assertEqual(cfg.mode, "auto")

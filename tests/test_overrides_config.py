import unittest

from model_effort_router.policy.config import DEFAULTS, resolve_config
from model_effort_router.policy.overrides import parse_override
from model_effort_router.profiles.profiles import Profile


class OverrideParsingTest(unittest.TestCase):
    def test_mode_only(self):
        o, rest = parse_override("/router off")
        self.assertEqual(o.mode, "off")
        self.assertEqual(rest, "")

    def test_stage_override_and_remaining_message(self):
        o, rest = parse_override("/router implement=frontier:high\nAdd endpoint")
        self.assertIsNone(o.mode)
        self.assertEqual(o.stages, {"implement": Profile("frontier", "high")})
        self.assertEqual(rest, "Add endpoint")

    def test_mode_and_multiple_stages(self):
        o, _ = parse_override("/router manual plan=frontier:xhigh review=frontier:high")
        self.assertEqual(o.mode, "manual")
        self.assertEqual(
            o.stages,
            {"plan": Profile("frontier", "xhigh"), "review": Profile("frontier", "high")},
        )

    def test_not_a_command_is_ignored(self):
        msgs = [
            "> /router off\nfix the bug",  # quoted
            "Please fix this:\n/router off",  # not first line
            "```\n/router off\n```",  # fenced paste
            " /router off",  # indented (pasted)
            "Here is the config: router: off",
            "router: off",
            "/routerx off",
            "see /router off for details",
        ]
        for m in msgs:
            with self.subTest(m=m):
                o, rest = parse_override(m)
                self.assertTrue(o.is_empty)
                self.assertEqual(rest, m)

    def test_invalid_command_is_rejected_entirely_and_line_stripped(self):
        for m in (
            "/router bogus",
            "/router implement=ultra:high",
            "/router implement=frontier",
            "/router deploy=frontier:high",
            "/router off implement=nope",
            "/router",
        ):
            with self.subTest(m=m):
                o, rest = parse_override(m + "\nAdd thing")
                self.assertTrue(o.is_empty)
                self.assertTrue(o.rejected)
                self.assertEqual(rest, "Add thing")

    def test_bare_or_whitespace_command_is_rejected_and_stripped(self):
        for first in ("/router", "/router ", "/router\r", "/router \t "):
            with self.subTest(first=first):
                o, rest = parse_override(first + "\nAdd thing")
                self.assertTrue(o.rejected)
                self.assertEqual(rest, "Add thing")

    def test_off_with_carriage_return(self):
        self.assertEqual(parse_override("/router off\r\nx")[0].mode, "off")

    def test_valid_and_non_commands_are_not_rejected(self):
        self.assertFalse(parse_override("/router off")[0].rejected)
        self.assertFalse(parse_override("/routerx off")[0].rejected)
        self.assertFalse(parse_override("fix it")[0].rejected)

    def test_none_and_empty(self):
        self.assertTrue(parse_override(None)[0].is_empty)
        self.assertTrue(parse_override("")[0].is_empty)


class ConfigPrecedenceTest(unittest.TestCase):
    def test_defaults(self):
        c = resolve_config()
        self.assertEqual(c.mode, "auto")
        self.assertEqual(c.backend, DEFAULTS["difficulty"]["backend"])
        self.assertEqual(c.fallback, "none")
        self.assertEqual(c.timeout_s, 10)

    def test_precedence_task_repo_user_defaults(self):
        user = {"router": {"mode": "manual"}, "difficulty": {"backend": "u", "timeout_s": 3}}
        repo = {"router": {"mode": "off"}, "difficulty": {"backend": "r"}}
        task = {"router": {"mode": "auto"}}
        c = resolve_config(task=task, repo=repo, user=user)
        self.assertEqual(c.mode, "auto")  # task beats repo beats user
        self.assertEqual(c.backend, "r")  # repo beats user
        self.assertEqual(c.timeout_s, 3)  # user beats defaults
        self.assertEqual(c.fallback, "none")  # default survives deep merge

    def test_repo_beats_user(self):
        c = resolve_config(repo={"router": {"mode": "off"}}, user={"router": {"mode": "manual"}})
        self.assertEqual(c.mode, "off")

    def test_inputs_not_mutated(self):
        repo = {"router": {"mode": "off"}}
        resolve_config(repo=repo)
        self.assertEqual(repo, {"router": {"mode": "off"}})
        self.assertEqual(DEFAULTS["router"]["mode"], "auto")

    def test_invalid_values_rejected(self):
        with self.assertRaises(ValueError):
            resolve_config(repo={"router": {"mode": "turbo"}})
        with self.assertRaises(ValueError):
            resolve_config(repo={"difficulty": {"timeout_s": 0}})

    def test_unknown_backend_names_rejected_when_registry_given(self):
        registry = {"a": None, "b": None}
        self.assertEqual(resolve_config(repo={"difficulty": {"backend": "a", "fallback": "b"}}, registry=registry).fallback, "b")
        for diff in ({"backend": "nope"}, {"backend": "a", "fallback": "nope"}):
            with self.subTest(diff=diff), self.assertRaises(ValueError):
                resolve_config(repo={"difficulty": diff}, registry=registry)

    def test_backend_names_validated_only_in_auto_mode(self):
        for mode in ("off", "manual"):
            c = resolve_config(repo={"router": {"mode": mode}, "difficulty": {"backend": "nope"}}, registry={})
            self.assertEqual(c.mode, mode)
        with self.assertRaises(ValueError):
            resolve_config(repo={"difficulty": {"backend": "nope"}}, registry={})

    def test_malformed_layers_rejected(self):
        for kwargs in (
            {"repo": ["x"]},
            {"user": "x"},
            {"repo": {"router": "off"}},
            {"repo": {"difficulty": ["subscription"]}},
            {"repo": {"difficulty": {"backend": 3}}},
            {"repo": {"difficulty": {"fallback": ["x"]}}},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                resolve_config(**kwargs)

    def test_bool_timeout_rejected(self):
        for bad in (True, False, "10", None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                resolve_config(repo={"difficulty": {"timeout_s": bad}})

    def test_override_to_config(self):
        o, _ = parse_override("/router off")
        self.assertEqual(resolve_config(task=o.as_config(), repo={"router": {"mode": "auto"}}).mode, "off")
        self.assertEqual(parse_override("/router implement=economy:medium")[0].as_config(), {})


if __name__ == "__main__":
    unittest.main()

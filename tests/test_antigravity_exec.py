import json
import unittest
from dataclasses import FrozenInstanceError

from model_effort_router.adapters.antigravity import AntigravityConfig, resolve
from model_effort_router.host import antigravity_exec as ax
from model_effort_router.profiles.profiles import Profile


class AdapterTest(unittest.TestCase):
    def test_default_models_and_abstract_efforts(self):
        for tier, model in (("economy", "gemini-3.8-flash"), ("balanced", "claude-sonnet-5-5"),
                            ("frontier", "claude-opus-5-5")):
            for requested, applied in (("medium", "medium"), ("high", "high"),
                                       ("xhigh", "high"), ("max", "high")):
                with self.subTest(tier=tier, requested=requested):
                    result = resolve(Profile(tier, requested))
                    self.assertEqual((result.tier, result.model, result.requested_effort, result.applied_effort),
                                     (tier, f"{model}-{applied}", requested, applied))

    def test_config_copies_and_freezes_maps(self):
        tiers = dict(AntigravityConfig().tiers)
        efforts = dict(AntigravityConfig().efforts)
        supported = {k: list(v) for k, v in AntigravityConfig().model_efforts.items()}
        config = AntigravityConfig(tiers, efforts, supported)
        tiers["economy"] = "changed"
        efforts["medium"] = "high"
        supported["gemini-3.8-flash"].clear()
        self.assertEqual(resolve(Profile("economy", "medium"), config).model, "gemini-3.8-flash-medium")
        with self.assertRaises(TypeError):
            config.tiers["economy"] = "changed"
        with self.assertRaises(FrozenInstanceError):
            config.tiers = {}

    def test_configuration_validation(self):
        cases = [{"tiers": {}}, {"efforts": {}}, {"tiers": None}, {"efforts": []}, {"model_efforts": None},
                 {"tiers": dict.fromkeys(("economy", "balanced", "frontier"), "unknown")},
                 {"efforts": {"medium": "medium", "high": "high", "xhigh": "xhigh", "max": "high"}},
                 {"model_efforts": {"gemini-3.8-flash": "high"}},
                 {"model_efforts": {"gemini-3.8-flash": ()}},
                 {"model_efforts": {"gemini-3.8-flash": ("xhigh",)}},
                 {"model_efforts": {"": ("high",)}}, {"model_efforts": {"--model": ("high",)}},
                 {"model_efforts": {"model name": ("high",)}}]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                AntigravityConfig(**kwargs)

    def test_supported_effort_fallback_uses_existing_rule(self):
        config = AntigravityConfig(model_efforts=dict.fromkeys(AntigravityConfig().model_efforts, ("high",)))
        self.assertEqual(resolve(Profile("economy", "medium"), config).model, "gemini-3.8-flash-high")


class ExecTest(unittest.TestCase):
    SUCCESS = {"conversation_id": "fixture-id", "status": "SUCCESS", "response": "done"}

    def test_result_contract(self):
        result = ax.parse_stream(json.dumps(self.SUCCESS))
        self.assertEqual((result.thread_id, result.text, result.usage), ("fixture-id", "done", None))
        with self.assertRaises(ax.AntigravityResultError):
            ax.parse_stream(json.dumps({**self.SUCCESS, "status": "ERROR"}))

    def test_invalid_envelopes_fail_closed(self):
        cases = [None, "", "not json", "[]", "null", "{}"]
        cases += [json.dumps({**self.SUCCESS, key: value}) for key, value in
                  (("status", "UNKNOWN"), ("conversation_id", ""), ("conversation_id", " "),
                   ("conversation_id", 1), ("response", None), ("usage", []), ("usage", None))]
        cases += [json.dumps({k: v for k, v in self.SUCCESS.items() if k != key})
                  for key in self.SUCCESS]
        for text in cases:
            with self.subTest(text=text), self.assertRaises(ax.AntigravityResultError):
                ax.parse_stream(text)

    def test_usage_is_validated_and_preserved_without_summing(self):
        usage = {"input_tokens": 100, "output_tokens": 20, "thinking_tokens": 10,
                 "cache_read_tokens": 50, "total_tokens": 120}
        parsed = ax.parse_stream(json.dumps({**self.SUCCESS, "usage": usage}))
        self.assertEqual(parsed.usage, usage)
        self.assertEqual(ax.parse_stream(json.dumps({**self.SUCCESS, "usage": {}})).usage, {})
        for key in usage:
            for value in (True, -1, 1.5, "10", None):
                with self.subTest(key=key, value=value), self.assertRaises(ax.AntigravityResultError):
                    ax.parse_stream(json.dumps({**self.SUCCESS, "usage": {key: value}}))

    def test_unverified_automation_is_explicitly_rejected(self):
        profile = Profile("economy", "medium")
        for sandbox in ("read-only", "workspace-write"):
            with self.assertRaisesRegex(ValueError, "unsupported"):
                ax.session_argv(profile, "request", sandbox)
        with self.assertRaisesRegex(ValueError, "unsupported"):
            ax.resume_argv(profile, "id", "request")

    def test_env_guard_is_a_copy(self):
        base = {"A": "1"}
        self.assertEqual(ax.session_env(base), {"A": "1", "MER_CLASSIFIER": "1"})
        self.assertEqual(base, {"A": "1"})


if __name__ == "__main__":
    unittest.main()

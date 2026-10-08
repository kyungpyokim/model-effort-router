import ast
import re
import unittest
from pathlib import Path

from model_effort_router.difficulty.efforts import EFFORTS, PROFILE_EFFORTS
from model_effort_router.profiles.profiles import EFFORTS as PROFILE_VALIDATION_EFFORTS


class EffortRegistryTests(unittest.TestCase):
    def test_profiles_use_canonical_effort_subset(self):
        self.assertEqual(PROFILE_EFFORTS, EFFORTS[1:])
        self.assertIs(PROFILE_VALIDATION_EFFORTS, PROFILE_EFFORTS)

    def test_opencode_schema_matches_canonical_efforts(self):
        source = Path(__file__).parents[1] / "plugins/opencode-model-effort-router/src/index.ts"
        match = re.search(r'effort:\s*\{\s*type:\s*"string",\s*enum:\s*(\[[^\]]*\])', source.read_text())
        self.assertIsNotNone(match)
        self.assertEqual(tuple(ast.literal_eval(match.group(1))), EFFORTS)

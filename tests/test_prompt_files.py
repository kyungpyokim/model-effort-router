import json
import unittest
from pathlib import Path
from string import Template

from model_effort_router import prompts

PROMPTS_DIR = Path(prompts.__file__).parent


class PromptFilesTest(unittest.TestCase):
    def test_render_fills_every_placeholder(self):
        text = prompts.render("summary", max_chars=2500, previous="PREV", turns="TURNS")
        self.assertIn("at most 2500 characters", text)
        self.assertTrue(text.endswith("New turns:\nTURNS"))
        self.assertNotIn("${", text)

    def test_a_missing_value_fails_loudly_instead_of_sending_a_broken_prompt(self):
        with self.assertRaises(KeyError):
            prompts.render("summary", max_chars=1, previous="p")

    def test_unknown_prompt_name_raises(self):
        with self.assertRaises(FileNotFoundError):
            prompts.render("no_such_prompt")

    def test_one_trailing_newline_is_not_part_of_the_prompt(self):
        for path in PROMPTS_DIR.glob("*.txt"):
            with self.subTest(prompt=path.name):
                raw = path.read_text(encoding="utf-8")
                self.assertTrue(raw.endswith("\n"), "keep the editor's final newline; the loader strips it")
                self.assertFalse(prompts.raw(path.stem).endswith("\n"))

    def test_templates_have_no_stray_dollar_signs(self):
        for path in PROMPTS_DIR.glob("*.txt"):
            with self.subTest(prompt=path.name):
                invalid = [
                    m for m in Template.pattern.finditer(prompts.raw(path.stem)) if m.group("invalid") is not None
                ]
                self.assertEqual(invalid, [], "escape a literal $ as $$")

    def test_fill_substitutes_strings_at_any_depth_and_keeps_other_values(self):
        doc = {"a": ["x ${v}", 1, None], "b": {"c": "${v}!"}}
        self.assertEqual(prompts.fill(doc, v="Z"), {"a": ["x Z", 1, None], "b": {"c": "Z!"}})
        self.assertEqual(doc["b"]["c"], "${v}!", "the parsed document is not modified")

    def test_data_files_keep_their_key_order_because_the_request_body_is_serialized_from_them(self):
        doc = prompts.data("jev_questions")
        self.assertEqual(list(doc), ["context_rule", "questions", "target"])
        self.assertEqual(list(doc["questions"]), ["role", "effort", "tier"])
        self.assertEqual(list(doc["questions"]["role"]), ["type", "instructions", "criteria"])

    def test_data_files_fill_cleanly_and_have_no_stray_dollar_signs(self):
        for path in PROMPTS_DIR.glob("*.json"):
            with self.subTest(prompt=path.name):
                doc = prompts.data(path.stem)
                filled = prompts.fill({k: v for k, v in doc.items() if k != "context_rule"}, context_rule="CR")
                self.assertNotIn("${", json.dumps(filled))


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path

from model_effort_router.gate.discovery import KINDS, discover


class DiscoveryTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def cmd(self, kind, config=None):
        c = discover(self.root, config)[kind]
        return (c.command, c.source) if c else None

    def test_nothing_found_all_none(self):
        found = discover(self.root)
        self.assertEqual(tuple(found), KINDS)
        self.assertTrue(all(v is None for v in found.values()))

    def test_explicit_config_beats_everything(self):
        self.write("AGENTS.md", "```\nnpm test\n```")
        self.write("package.json", json.dumps({"scripts": {"test": "jest"}}))
        self.assertEqual(self.cmd("test", {"test": "make check"}), ("make check", "config"))

    def test_config_unknown_kind_rejected(self):
        with self.assertRaises(ValueError):
            discover(self.root, {"tset": "x"})
        with self.assertRaises(ValueError):
            discover(self.root, {"test": 5})

    def test_agents_md_fenced_beats_manifest(self):
        self.write("AGENTS.md", "Run:\n```sh\n$ python3 -m unittest discover -s tests -v\nruff check .\n```")
        self.write("package.json", json.dumps({"scripts": {"test": "jest"}}))
        self.assertEqual(self.cmd("test"), ("python3 -m unittest discover -s tests -v", "AGENTS.md"))
        self.assertEqual(self.cmd("lint"), ("ruff check .", "AGENTS.md"))

    def test_inline_code_in_prose_ignored_agents_before_claude(self):
        self.write("CLAUDE.md", "Tests: `pytest -q`")
        self.assertIsNone(self.cmd("test"))
        self.write("CLAUDE.md", "```\npytest -q\n```")
        self.assertEqual(self.cmd("test"), ("pytest -q", "CLAUDE.md"))
        self.write("AGENTS.md", "```\nnpm test\n```")
        self.assertEqual(self.cmd("test"), ("npm test", "AGENTS.md"))

    def test_glob_commands_skipped(self):
        self.write("AGENTS.md", "```\npytest tests/*.py\nnpm test\n```")
        self.assertEqual(self.cmd("test"), ("npm test", "AGENTS.md"))
        self.write("AGENTS.md", "```\npytest tests/test_?.py\n```")
        self.assertIsNone(self.cmd("test"))

    def test_shell_operators_and_prose_skipped(self):
        self.write("AGENTS.md", "```\nnpm test && rm -rf /\ncat x | pytest\n```\nRun the tests with pytest.")
        self.assertIsNone(self.cmd("test"))

    def test_ci_file(self):
        self.write(
            ".github/workflows/ci.yml", "jobs:\n  t:\n    steps:\n      - run: go test ./...\n      - run: mypy src\n"
        )
        self.assertEqual(self.cmd("test"), ("go test ./...", ".github/workflows/ci.yml"))
        self.assertEqual(self.cmd("typecheck"), ("mypy src", ".github/workflows/ci.yml"))

    def test_docs_beat_ci(self):
        self.write("AGENTS.md", "```\nmake test\n```")
        self.write(".github/workflows/ci.yml", "      - run: go test ./...\n")
        self.assertEqual(self.cmd("test")[1], "AGENTS.md")

    def test_package_json_scripts(self):
        self.write(
            "package.json",
            json.dumps(
                {"scripts": {"test": "jest", "lint": "eslint .", "type-check": "tsc --noEmit", "build": "vite build"}}
            ),
        )
        self.assertEqual(self.cmd("test"), ("npm test", "package.json"))
        self.assertEqual(self.cmd("lint"), ("npm run lint", "package.json"))
        self.assertEqual(self.cmd("typecheck"), ("npm run type-check", "package.json"))
        self.assertEqual(self.cmd("build"), ("npm run build", "package.json"))

    def test_package_json_default_placeholder_test_ignored_and_bad_json_survives(self):
        self.write("package.json", json.dumps({"scripts": {"test": 'echo "Error: no test specified" && exit 1'}}))
        self.assertIsNone(self.cmd("test"))
        self.write("package.json", "{broken")
        self.assertIsNone(self.cmd("test"))

    def test_pyproject_and_makefile(self):
        self.write("pyproject.toml", "[tool.pytest.ini_options]\nx=1\n[tool.ruff]\n[tool.mypy]\n")
        self.assertEqual(self.cmd("test"), ("python3 -m pytest", "pyproject.toml"))
        self.assertEqual(self.cmd("lint"), ("ruff check .", "pyproject.toml"))
        self.assertEqual(self.cmd("typecheck"), ("mypy .", "pyproject.toml"))
        self.write("Makefile", "build:\n\tcc x\n\nlint:\n\techo\n")
        self.assertEqual(self.cmd("build"), ("make build", "Makefile"))
        self.assertEqual(self.cmd("lint")[1], "pyproject.toml")  # pyproject precedes Makefile

    def test_non_dict_config_treated_as_none(self):
        self.assertIsNone(discover(self.root, None)["test"])


if __name__ == "__main__":
    unittest.main()

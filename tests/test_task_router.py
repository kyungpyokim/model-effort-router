from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tomllib
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


evaluator = load_script("eval_task_router")
validator = load_script("validate_bundle")


def frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---"
    end = lines.index("---", 1)
    return dict(line.split(": ", 1) for line in lines[1:end])


class ClaudeTaskRouterTests(unittest.TestCase):
    def test_agents_declare_required_fields_and_role_effort(self):
        expected_effort = {
            "research": "low",
            "coding": "medium",
            "review": "high",
            "complex": "xhigh",
        }
        agents = ROOT / "plugins" / "claude-task-router" / "agents"
        for name, effort in expected_effort.items():
            with self.subTest(agent=name):
                data = frontmatter(agents / f"{name}.md")
                self.assertEqual(data["name"], name)
                self.assertTrue(data["description"])
                self.assertTrue(data["tools"])
                self.assertTrue(data["model"])
                self.assertEqual(data["effort"], effort)

    def test_readme_uses_scoped_agent_name_without_overclaiming_effective_effort(self):
        readme = (ROOT / "plugins" / "claude-task-router" / "README.md").read_text(encoding="utf-8")
        self.assertIn("task-router:coding", readme)
        self.assertNotIn("falls back to opus", readme)
        self.assertIn("static configuration", readme)
        self.assertNotIn("intended model and effort", readme)
        self.assertIn("2.1.267+", readme)
        self.assertIn("saved effort hold", readme)

    def test_evaluator_docstring_does_not_claim_to_verify_effective_effort(self):
        self.assertIn("does not verify effective Claude effort", evaluator.__doc__)

    def test_claude_error_payload_is_a_failed_result(self):
        completed = subprocess.CompletedProcess(
            [],
            0,
            json.dumps({"is_error": True, "modelUsage": {"sonnet": {"inputTokens": 1}}}),
            "",
        )
        case = evaluator.AgentCase("claude", "coding", "sonnet", "medium")
        with mock.patch.object(evaluator.subprocess, "run", return_value=completed) as run:
            result = evaluator.run_claude(case)
        self.assertFalse(result["ok"])
        self.assertIn("is_error", result["stderr_tail"])
        self.assertEqual(run.call_args.args[0][run.call_args.args[0].index("--agent") + 1], "task-router:coding")

    def test_claude_timeout_is_a_failed_result(self):
        case = evaluator.AgentCase("claude", "coding", "sonnet", "medium")
        with mock.patch.object(evaluator.subprocess, "run", side_effect=subprocess.TimeoutExpired([], 1)):
            result = evaluator.run_claude(case)
        self.assertFalse(result["ok"])
        self.assertIn("timed out", result["stderr_tail"])

    def test_empty_agent_selection_returns_error(self):
        with (
            mock.patch.object(evaluator, "load_codex_agents", return_value=[]),
            mock.patch.object(evaluator, "load_claude_agents", return_value=[]),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(evaluator.main([]), 2)

    def test_loader_preserves_claude_agent_effort(self):
        self.assertEqual(
            {case.name: case.effort for case in evaluator.load_claude_agents()},
            {"coding": "medium", "complex": "xhigh", "research": "low", "review": "high"},
        )

    def test_codex_agents_define_expected_runtime_contract(self):
        expected = {
            "coding": ("gpt-5.6-terra", "medium", "workspace-write"),
            "complex": ("gpt-6-astra", "high", "workspace-write"),
            "research": ("gpt-5.6-luna", "high", "read-only"),
        }
        agents = ROOT / "plugins" / "codex-task-router" / "agents"
        self.assertEqual({path.stem for path in agents.glob("*.toml")}, set(expected))
        for name, values in expected.items():
            with self.subTest(agent=name):
                data = tomllib.loads((agents / f"{name}.toml").read_text(encoding="utf-8"))
                self.assertEqual(
                    (data["model"], data["model_reasoning_effort"], data["sandbox_mode"]),
                    values,
                )

    def test_validator_checks_task_router_and_codex_agent_contracts(self):
        source = (ROOT / "scripts" / "validate_bundle.py").read_text(encoding="utf-8")
        self.assertIn("claude-task-router", source)
        self.assertIn("codex-task-router", source)
        self.assertIn("tomllib", source)
        self.assertIn("effort", source)
        self.assertIn("sandbox_mode", source)
        self.assertEqual(validator.main(), 0)


if __name__ == "__main__":
    unittest.main()

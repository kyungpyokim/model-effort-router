#!/usr/bin/env python3
"""Static validation for the cross-platform plugin bundle."""
from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path


def require(path: Path) -> None:
    if not path.exists():
        raise AssertionError(f"missing: {path}")


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---", f"missing frontmatter: {path}"
    end = lines.index("---", 1)
    return dict(line.split(": ", 1) for line in lines[1:end])


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    require(root / "config" / "model-map.json")

    codex = root / "plugins" / "codex-model-effort-router"
    claude = root / "plugins" / "claude-model-effort-router"
    agy = root / "plugins" / "antigravity-model-effort-router"

    c_manifest = read_json(codex / ".codex-plugin" / "plugin.json")
    assert c_manifest["name"] == "model-effort"
    assert c_manifest["version"] == "2.2.0"
    require(codex / "skills" / "route" / "SKILL.md")
    require(codex / "hooks" / "hooks.json")
    require(codex / "scripts" / "routing_policy_hook.py")
    codex_hooks = read_json(codex / "hooks" / "hooks.json")["hooks"]
    assert set(codex_hooks) == {"SessionStart"}
    handler = codex_hooks["SessionStart"][0]["hooks"][0]
    assert handler["timeout"] == 2
    assert handler["additionalContextLimit"] == 1000
    assert "routing_policy_hook.py" in handler["command"]
    assert not handler.get("async", False)
    assert "hooks" not in c_manifest
    assert len(list((codex / "agents").glob("*.toml"))) >= 7

    a_manifest = read_json(claude / ".claude-plugin" / "plugin.json")
    assert a_manifest["name"] == "model-effort"
    assert a_manifest["version"] == "2.2.0"
    require(claude / "skills" / "route" / "SKILL.md")
    assert len(list((claude / "agents").glob("*.md"))) >= 7
    assessor = read_frontmatter(claude / "agents" / "difficulty-assessor.md")
    assert assessor["name"] == "difficulty-assessor", "invalid assessor agent name"
    assert assessor["tools"] == "Read, Grep, Glob", "the difficulty assessor must stay read-only"
    # The route skill delegates through the Agent tool, which cannot set effort,
    # so each matrix effort needs an agent that pins it.
    for effort in ("none", "low", "medium", "high", "xhigh", "max"):
        agent = read_frontmatter(claude / "agents" / f"effort-{effort}.md")
        assert agent["name"] == f"effort-{effort}", f"invalid effort agent name: {effort}"
        assert agent.get("effort") == (None if effort == "none" else effort), f"invalid effort agent effort: {effort}"

    task_router = root / "plugins" / "claude-task-router"
    task_manifest = read_json(task_router / ".claude-plugin" / "plugin.json")
    assert task_manifest["name"] == "task-router"
    assert task_manifest["version"] == "1.0.0"
    required_agent_fields = {"name", "description", "tools", "model", "effort"}
    valid_efforts = {"low", "medium", "high", "xhigh", "max"}
    task_agents = list((task_router / "agents").glob("*.md"))
    assert len(task_agents) == 4
    for path in task_agents:
        agent = read_frontmatter(path)
        assert required_agent_fields <= agent.keys(), f"missing agent field: {path}"
        assert agent["name"] == path.stem, f"agent name does not match file: {path}"
        assert agent["effort"] in valid_efforts, f"invalid effort: {path}"

    codex_task_router = root / "plugins" / "codex-task-router"
    expected_sandbox_modes = {
        "coding": "workspace-write",
        "complex": "workspace-write",
        "research": "read-only",
    }
    valid_models = {"gpt-5.6-luna", "gpt-5.6-terra", "gpt-6-astra"}
    codex_agents = {path.stem: path for path in (codex_task_router / "agents").glob("*.toml")}
    assert set(codex_agents) == set(expected_sandbox_modes)
    for name, path in codex_agents.items():
        agent = tomllib.loads(path.read_text(encoding="utf-8"))
        assert {"model", "model_reasoning_effort", "sandbox_mode"} <= agent.keys(), f"missing agent field: {path}"
        assert agent["model"] in valid_models, f"invalid model: {path}"
        assert agent["model_reasoning_effort"] in valid_efforts, f"invalid effort: {path}"
        assert agent["sandbox_mode"] == expected_sandbox_modes[name], f"invalid sandbox: {path}"

    g_manifest = read_json(agy / "gemini-extension.json")
    assert g_manifest["name"] == "model-effort"
    assert g_manifest["version"] == "2.2.0"
    require(agy / "skills" / "route" / "SKILL.md")
    require(agy / "GEMINI.md")
    require(agy / "commands" / "route.toml")
    require(agy / "bin" / "agy-route")

    print("bundle validation passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        raise

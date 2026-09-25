#!/usr/bin/env python3
"""Static validation for the cross-platform plugin bundle."""
from __future__ import annotations

import importlib.util
import json
import sys
import tomllib
from pathlib import Path


def load_router(root: Path):
    path = root / "scripts" / "router.py"
    # Reuse a router already loaded from this file: executing it again registers a second module
    # under the same name, orphaning the first copy so patched instances and tests split apart.
    loaded = sys.modules.get("router")
    if loaded is not None and getattr(loaded, "__file__", None) == str(path):
        return loaded
    spec = importlib.util.spec_from_file_location("router", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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

    router = load_router(root)
    model_map = read_json(root / "config" / "model-map.json")
    classifiers = model_map["classifiers"]
    # Only one classifier class exists: unknown facts are settled by one bounded lookup or a question,
    # never by a stronger classifier. antigravity's patterns are not asserted (they follow the detected models).
    assert all(set(entry) == {"primary"} for entry in classifiers.values()), "model-map classifiers must only define a primary"
    for platform in ("codex", "claude-code"):
        assert classifiers[platform]["primary"] == router.PRIMARY_CLASSIFIER_CONFIG[platform], (
            f"model-map classifiers.{platform}.primary does not match router.PRIMARY_CLASSIFIER_CONFIG"
        )

    # The cascade is gone: no shipped doc may still describe needs_context or an escalated classifier.
    for doc in (
        *(root / "plugins").glob("*/README.md"), *(root / "plugins").glob("*/references/routing-policy.md"),
        root / "README.md", root / "README.ko.md", root / "references" / "routing-policy.md",
    ):
        assert "needs_context" not in doc.read_text(encoding="utf-8"), f"{doc.relative_to(root)} still describes needs_context"
    assert tuple(model_map["levels"]) == router.LEVELS, "model-map levels must match router.LEVELS"
    for tier in router.RISK_TIERS[1:]:
        assert set(model_map["tiers"][tier]) == set(classifiers), f"model-map tiers.{tier} must cover every platform"

    codex = root / "plugins" / "codex-model-effort-router"
    claude = root / "plugins" / "claude-model-effort-router"
    agy = root / "plugins" / "antigravity-model-effort-router"

    c_manifest = read_json(codex / ".codex-plugin" / "plugin.json")
    assert c_manifest["name"] == "model-effort"
    assert c_manifest["version"] == "3.1.0"
    for key in ("logo", "logoDark", "composerIcon"):
        relative = c_manifest["interface"][key]
        assert relative.startswith("./"), f"interface.{key} must be a plugin-relative path"
        require(codex / relative[2:])
    require(codex / "skills" / "route" / "SKILL.md")
    require(codex / "hooks" / "hooks.json")
    require(codex / "scripts" / "routing_policy_hook.py")
    for plugin in (codex, claude, agy):
        require(plugin / "scripts" / "pipeline.py")
        require(plugin / "scripts" / "route_reuse.py")
        require(plugin / "scripts" / "jev_provider.py")
        # The policy links the ceiling doc; the bundle copy must exist or the link dangles.
        require(plugin / "docs" / "routing-ceiling.md")
        assert (plugin / "docs" / "routing-ceiling.md").read_bytes() == (root / "docs" / "routing-ceiling.md").read_bytes(), (
            f"{plugin.name}/docs/routing-ceiling.md is stale; run scripts/sync_bundle.py"
        )
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
    assert a_manifest["version"] == "3.1.0"
    require(claude / "skills" / "route" / "SKILL.md")
    require(claude / "scripts" / "routing_policy_hook.py")
    claude_hooks = read_json(claude / "hooks" / "hooks.json")["hooks"]
    assert set(claude_hooks) == {"SessionStart"}
    claude_handler = claude_hooks["SessionStart"][0]["hooks"][0]
    assert claude_handler["timeout"] == 2
    assert "${CLAUDE_PLUGIN_ROOT}/scripts/routing_policy_hook.py" in claude_handler["command"]
    assert not claude_handler.get("async", False)
    assert "hooks" not in a_manifest
    assert len(list((claude / "agents").glob("*.md"))) >= 7
    assessor = read_frontmatter(claude / "agents" / "difficulty-assessor.md")
    assert assessor["name"] == "difficulty-assessor", "invalid assessor agent name"
    assert assessor["tools"] == "Read, Grep, Glob", "the difficulty assessor must stay read-only"
    assert int(assessor["maxTurns"]) >= 16, "the difficulty assessor needs turns to finish its JSON"
    assert "at most 6 tool calls" in (claude / "agents" / "difficulty-assessor.md").read_text(encoding="utf-8")
    claude_skill_text = (claude / "skills" / "route" / "SKILL.md").read_text(encoding="utf-8")
    assert "`model` `haiku`" in claude_skill_text, "primary classification step must stay on haiku"
    assert "`model` `opus`" not in claude_skill_text, "unknown facts are never settled by a stronger classifier"
    assert "unresolved_facts" in claude_skill_text, "the route skill must ask the user about unresolved facts"
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
    valid_models = {"gpt-6-luna", "gpt-6-sol"}
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
    assert g_manifest["version"] == "3.1.0"
    # The Antigravity bundle ships two version-bearing manifests; a release that bumps only one
    # reports a stale version to whichever client reads the other.
    agy_plugin = read_json(agy / "plugin.json")
    assert agy_plugin["name"] == "model-effort"
    assert agy_plugin["version"] == g_manifest["version"], "antigravity plugin.json and gemini-extension.json versions differ"
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

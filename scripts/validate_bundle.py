#!/usr/bin/env python3
"""Static validation for the cross-platform plugin bundle."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def require(path: Path) -> None:
    if not path.exists():
        raise AssertionError(f"missing: {path}")


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    require(root / "config" / "model-map.json")

    codex = root / "plugins" / "codex-model-effort-router"
    claude = root / "plugins" / "claude-model-effort-router"
    agy = root / "plugins" / "antigravity-model-effort-router"

    c_manifest = read_json(codex / ".codex-plugin" / "plugin.json")
    assert c_manifest["name"] == "model-effort"
    assert c_manifest["hooks"] == "./hooks/hooks.json"
    require(codex / "hooks" / "hooks.json")
    require(codex / "skills" / "route" / "SKILL.md")
    assert len(list((codex / "agents").glob("*.toml"))) == 5

    a_manifest = read_json(claude / ".claude-plugin" / "plugin.json")
    assert a_manifest["name"] == "model-effort"
    require(claude / "hooks" / "hooks.json")
    require(claude / "skills" / "route" / "SKILL.md")
    assert len(list((claude / "agents").glob("*.md"))) == 5

    g_manifest = read_json(agy / "gemini-extension.json")
    assert g_manifest["name"] == "model-effort"
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

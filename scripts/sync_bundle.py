#!/usr/bin/env python3
"""Propagate the bundle-root shared files into each platform plugin copy."""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

SHARED = ("scripts/router.py", "config/model-map.json", "references/routing-policy.md")
PLUGINS = (
    "plugins/codex-model-effort-router",
    "plugins/claude-model-effort-router",
    "plugins/antigravity-model-effort-router",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    for relative in SHARED:
        source = root / relative
        if not source.exists():
            print(f"missing bundle file: {source}", file=sys.stderr)
            return 1
        expected = digest(source)
        for plugin in PLUGINS:
            target = root / plugin / relative
            if target.exists() and digest(target) == expected:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            print(f"synced {plugin}/{relative}")
    print("bundle copies are in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

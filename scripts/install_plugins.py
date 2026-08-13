#!/usr/bin/env python3
"""Install one or all Model Effort Router plugins from this bundle."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path


def run(cmd: list[str], dry_run: bool) -> None:
    print("+", " ".join(str(x) for x in cmd))
    if not dry_run:
        subprocess.run(cmd, check=True)


def install_codex(bundle: Path, dry_run: bool) -> None:
    codex = shutil.which("codex") or "codex"
    run([codex, "plugin", "marketplace", "add", str(bundle)], dry_run)
    run([codex, "plugin", "add", "model-effort@model-effort-router-bundle"], dry_run)
    print("Codex local marketplace support can vary by client version. Use plugins/codex-model-effort-router/bin/codex-route when agent routing is not honored.")


def install_claude(bundle: Path, scope: str, dry_run: bool) -> None:
    claude = shutil.which("claude") or "claude"
    run([claude, "plugin", "marketplace", "add", str(bundle), "--scope", scope], dry_run)
    run([claude, "plugin", "install", "model-effort@model-effort-router-bundle", "--scope", scope], dry_run)


def install_antigravity(bundle: Path, dry_run: bool) -> None:
    agy = shutil.which("agy") or "agy"
    plugin = bundle / "plugins" / "antigravity-model-effort-router"
    run([agy, "plugin", "install", str(plugin)], dry_run)
    wrapper = (plugin / "bin" / "agy-route").resolve()
    target = Path.home() / ".local" / "bin" / "agy-route"
    if dry_run:
        print("+ symlink", wrapper, "->", target)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.exists():
        existing = os.readlink(target) if target.is_symlink() else str(target)
        print(f"replacing existing launcher at {target} (was: {existing})")
        target.unlink()
    # Symlink rather than copy: the launcher locates scripts/router.py relative to
    # its own real path, so a plain copy into ~/.local/bin would break it.
    target.symlink_to(wrapper)
    print(f"installed deterministic launcher -> {target} -> {wrapper}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=("codex", "claude-code", "antigravity", "all"))
    parser.add_argument("--scope", choices=("user", "project", "local"), default="user", help="Claude Code installation scope")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    bundle = Path(__file__).resolve().parent.parent
    targets = ("codex", "claude-code", "antigravity") if args.target == "all" else (args.target,)
    for target in targets:
        if target == "codex":
            install_codex(bundle, args.dry_run)
        elif target == "claude-code":
            install_claude(bundle, args.scope, args.dry_run)
        else:
            install_antigravity(bundle, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

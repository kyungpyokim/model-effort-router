"""Copy the core package into BOTH plugin bundles (codex, claude). `--check` (default in tests) only reports drift."""
import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "model_effort_router"
PLUGINS = ROOT / "plugins"
BUNDLES = [PLUGINS / "codex-model-effort-router" / "model_effort_router",
           PLUGINS / "claude-model-effort-router" / "model_effort_router"]  # both get an identical core copy


def _files(base):
    return sorted(p.relative_to(base).as_posix() for p in base.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")


def check():
    drift = []
    for dst_dir in BUNDLES:
        tag = dst_dir.parent.name
        src, dst = _files(SRC), _files(dst_dir) if dst_dir.exists() else []
        drift += [f"{tag}: missing in plugin: {f}" for f in sorted(set(src) - set(dst))]
        drift += [f"{tag}: extra in plugin: {f}" for f in sorted(set(dst) - set(src))]
        drift += [f"{tag}: differs: {f}" for f in sorted(set(src) & set(dst))
                  if not filecmp.cmp(SRC / f, dst_dir / f, shallow=False)]
    return drift


def sync():
    for dst_dir in BUNDLES:
        if dst_dir.exists():
            shutil.rmtree(dst_dir)
        shutil.copytree(SRC, dst_dir, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


if __name__ == "__main__":
    if "--check" in sys.argv:
        problems = check()
        print("\n".join(problems) or "in sync")
        sys.exit(1 if problems else 0)
    sync()

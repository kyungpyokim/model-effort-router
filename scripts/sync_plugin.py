"""Copy the core package into the plugin bundle. `--check` (default in tests) only reports drift."""
import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "model_effort_router"
PLUGIN = ROOT / "plugins" / "codex-model-effort-router"
DST = PLUGIN / "model_effort_router"


def _files(base):
    return sorted(p.relative_to(base).as_posix() for p in base.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")


def check():
    drift = []
    src, dst = _files(SRC), _files(DST) if DST.exists() else []
    drift += [f"missing in plugin: {f}" for f in sorted(set(src) - set(dst))]
    drift += [f"extra in plugin: {f}" for f in sorted(set(dst) - set(src))]
    drift += [f"differs: {f}" for f in sorted(set(src) & set(dst))
              if not filecmp.cmp(SRC / f, DST / f, shallow=False)]
    return drift


def sync():
    if DST.exists():
        shutil.rmtree(DST)
    shutil.copytree(SRC, DST, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


if __name__ == "__main__":
    if "--check" in sys.argv:
        problems = check()
        print("\n".join(problems) or "in sync")
        sys.exit(1 if problems else 0)
    sync()

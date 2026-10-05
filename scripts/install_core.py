"""Install the one shared router core; plugin bundles contain only host integration."""
import argparse
import filecmp
import os
import shutil
import sys
import tempfile
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "model_effort_router"


def runtime_path(env=None):
    env = os.environ if env is None else env
    home = Path(env.get("HOME") or Path.home())
    xdg = Path(env.get("XDG_DATA_HOME") or home / ".local/share")
    base = xdg if xdg.is_absolute() else home / ".local/share"
    runtime = Path(env.get("MER_CORE_PATH") or base / "model-effort-router/runtime")
    if not runtime.is_absolute():
        raise ValueError("MER_CORE_PATH must be an absolute directory containing model_effort_router/")
    return runtime


def _files(package):
    return sorted(p.relative_to(package).as_posix() for p in package.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")


def check(source, runtime):
    target = Path(runtime) / "model_effort_router"
    src, dst = set(_files(Path(source))), set(_files(target))
    return ([f"missing: {p}" for p in sorted(src - dst)]
            + [f"extra: {p}" for p in sorted(dst - src)]
            + [f"differs: {p}" for p in sorted(src & dst)
               if not filecmp.cmp(Path(source) / p, target / p, shallow=False)])


def install(source, runtime):
    source, runtime = Path(source).resolve(), Path(runtime).resolve()
    target = runtime / "model_effort_router"
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("source and installed core must not overlap")
    if not all((source / name).is_file() for name in ("__init__.py", "entrypoints.py")):
        raise ValueError("source is not a router core package")
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise ValueError("installed core must be a directory, not a file or symlink")
    runtime.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".mer-install-", dir=runtime))
    backup = stage / "previous"
    try:
        staged = stage / "model_effort_router"
        shutil.copytree(source, staged, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        if check(source, stage):
            raise OSError("staged core differs from source")
        if target.exists():
            target.rename(backup)
        try:
            staged.rename(target)
        except BaseException:
            if backup.exists():
                backup.rename(target)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    finally:
        # A failed rollback must leave the previous package recoverable.
        if not backup.exists():
            shutil.rmtree(stage)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report source/runtime differences without installing")
    args = parser.parse_args(argv)
    try:
        runtime = runtime_path()
        if args.check:
            problems = check(SOURCE, runtime)
            print("\n".join(problems) or "in sync")
            return int(bool(problems))
        install(SOURCE, runtime)
        print(f"Shared core installed: {runtime}")
        return 0
    except (ValueError, OSError) as exc:
        print(f"Shared core installation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

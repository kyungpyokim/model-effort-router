"""Meta-tests for the frozen L1/L2 execution-corpus fixture repositories.

Each fixture is a self-contained miniature repository whose frozen test command
must run locally, offline, and deterministically from a fresh copy. These tests
check fixture isolation/contract properties only; they never solve a fixture
task. The parameterization is derived from the frozen manifest, never
hand-written, so fixture metadata cannot drift from `cases.json`.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import e2e_corpus  # noqa: E402

MANIFEST_PATH = ROOT / "evals" / "execution_corpus" / "cases.json"
LEVELS_UNDER_TEST = ("L1", "L2")
RUN_TIMEOUT_SECONDS = 120
EXPECTED_OUTCOME_PATTERN = re.compile(
    r"Expected initial test outcome:\s*(?P<label>[A-Z]+)\s*\(pytest exit status (?P<code>\d+)\)"
)
SUMMARY_COUNT_PATTERN = re.compile(r"(\d+) (passed|failed|error|skipped)")
NETWORK_IMPORT_PATTERN = re.compile(
    r"^[ \t]*(?:import|from)[ \t]+([A-Za-z_][\w.]*)", re.MULTILINE
)
# Fixtures must be fully offline: any import below (or below one of its
# submodules) could reach the network, so none of them may appear.
BANNED_NETWORK_MODULES = (
    "aiohttp",
    "ftplib",
    "http",
    "requests",
    "smtplib",
    "socket",
    "telnetlib",
    "urllib",
    "webbrowser",
)

CASES = tuple(
    case
    for case in e2e_corpus.load_execution_cases(MANIFEST_PATH)
    if case.level in LEVELS_UNDER_TEST
)
CASE_IDS = [case.name for case in CASES]
CASES_BY_NAME = {case.name: case for case in CASES}


def fixture_root(case: e2e_corpus.ExecutionCase) -> Path:
    """Absolute path of the frozen fixture directory for one case."""
    root = ROOT / case.fixture_dir
    assert root.is_dir(), f"missing fixture directory for {case.name}: {root}"
    return root


def iter_entries(root: Path):
    """Every entry under root, without following directory symlinks."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames + filenames:
            yield Path(dirpath) / name


def network_imports(text: str) -> list[str]:
    """Banned network modules imported by one source file, sorted."""
    found = {
        module
        for module in NETWORK_IMPORT_PATTERN.findall(text)
        if any(
            module == banned or module.startswith(banned + ".")
            for banned in BANNED_NETWORK_MODULES
        )
    }
    return sorted(found)


def classify(pytest_output: str) -> dict[str, int]:
    """Counts from the pytest summary line, ignoring timings and paths."""
    counts: dict[str, int] = {}
    for value, name in SUMMARY_COUNT_PATTERN.findall(pytest_output):
        counts[name] = int(value)
    return counts


def subprocess_env() -> dict[str, str]:
    """Minimal hermetic environment for launching a fixture test command."""
    return {
        "PATH": os.environ.get("PATH", ""),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
    }


@lru_cache(maxsize=None)
def run_initial_state(case_name: str, attempt: int) -> tuple[int, dict[str, int], str]:
    """Run a case's frozen test_cmd from a fresh copy of its fixture.

    Cached per (case, attempt) so the launch test and the determinism test
    share runs: two fresh copies per case for the whole pytest session.
    """
    case = CASES_BY_NAME[case_name]
    with tempfile.TemporaryDirectory(prefix=f"exec-corpus-{case_name}-{attempt}-") as tmp:
        copy = Path(tmp) / "fixture"
        shutil.copytree(ROOT / case.fixture_dir, copy, symlinks=True)
        process = subprocess.run(
            shlex.split(case.test_cmd),
            cwd=copy,
            env=subprocess_env(),
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT_SECONDS,
        )
    output = process.stdout + process.stderr
    return process.returncode, classify(output), output


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_fixture_directory_exists(case):
    fixture_root(case)


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_no_symlink_escapes_the_fixture_root(case):
    root = fixture_root(case)
    assert not root.is_symlink(), f"{root} must be a real directory, not a symlink"

    resolved_root = root.resolve()
    escapes = [
        str(entry)
        for entry in iter_entries(root)
        if entry.is_symlink() and not entry.resolve().is_relative_to(resolved_root)
    ]

    assert escapes == [], f"symlinks escaping the fixture root: {escapes}"


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_fixture_never_touches_the_network(case):
    root = fixture_root(case)
    offenders: dict[str, list[str]] = {}
    for path in sorted(root.rglob("*.py")):
        found = network_imports(path.read_text(encoding="utf-8"))
        if found:
            offenders[str(path.relative_to(root))] = found

    assert offenders == {}, f"network imports found in fixture: {offenders}"


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_test_command_launches_locally(case):
    returncode, counts, output = run_initial_state(case.name, 0)

    assert returncode in (0, 1), (
        f"{case.test_cmd} must run locally against a fresh fixture copy "
        f"(exit status {returncode}):\n{output[-2000:]}"
    )
    assert counts, f"test_cmd produced no pytest summary:\n{output[-2000:]}"


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_initial_state_is_deterministic_across_fresh_copies(case):
    readme = fixture_root(case) / "README.md"
    assert readme.is_file(), f"{case.name} fixture must document its expected initial outcome"
    match = EXPECTED_OUTCOME_PATTERN.search(readme.read_text(encoding="utf-8"))
    assert match, f"{readme} must record 'Expected initial test outcome: ...'"

    first_code, first_counts, first_output = run_initial_state(case.name, 0)
    second_code, second_counts, second_output = run_initial_state(case.name, 1)

    assert first_code == second_code, (
        f"exit status drifted across fresh copies: {first_code} vs {second_code}\n"
        f"run 1:\n{first_output[-1000:]}\nrun 2:\n{second_output[-1000:]}"
    )
    assert first_counts == second_counts, (
        f"outcome classification drifted across fresh copies: "
        f"{first_counts} vs {second_counts}"
    )

    assert match.group("label") == "FAIL", "initial state must exhibit the target defect"
    assert first_code == int(match.group("code")), (
        f"declared initial exit status {match.group('code')} != observed {first_code}"
    )
    assert first_counts.get("failed", 0) >= 1, (
        f"initial state must fail the acceptance tests:\n{first_output[-2000:]}"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

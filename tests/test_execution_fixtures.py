"""Meta-tests for the frozen L1-L3 execution-corpus fixture repositories.

Each fixture is a self-contained miniature repository whose frozen test command
must run locally, offline, and deterministically from a fresh copy. The tests
check fixture isolation/contract properties; for every L3 case they also prove
the acceptance test distinguishes the initial state from a known-correct patch
(the distinguishing verification sanctioned for Task 3). Those patches live
only in this file and are applied to throwaway tmp copies — the committed
fixture directories stay unsolved, so a benchmark run never sees a solution.
Parameterization is derived from the frozen manifest, never hand-written, so
fixture metadata cannot drift from `cases.json`.
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
LEVELS_UNDER_TEST = ("L1", "L2", "L3")
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


# The duplicated parsing helper the L3 refactor must collapse into one place.
SHARED_SPLIT_PAIR = '''def _split_pair(text: str, sep: str) -> tuple[str, str]:
    """Split one key/value pair and drop surrounding quotes from the value."""
    key, _, value = text.partition(sep)
    return key.strip(), value.strip().strip('"')
'''

# Sanctioned exception to "gold fixes not committed": one minimal known-correct
# patch per L3 case, embedded here (never under fixtures/) and applied only to
# fresh tmp copies. Each step is (relative path, anchor text, replacement); an
# empty anchor means "create this file with the given content", otherwise the
# anchor must occur exactly once so a patch can never silently diverge from the
# fixture snapshot a benchmark model actually receives.
GOLD_FIXES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "L3_add_feature_controller_service": (
        (
            "promo_service.py",
            '''def validate_promo(code: str) -> str:
    """Return the normalized promo code, or raise ValueError when invalid."""
    return code
''',
            '''def validate_promo(code: str) -> str:
    """Return the normalized promo code, or raise ValueError when invalid."""
    normalized = code.strip().upper()
    if not normalized:
        raise ValueError("promo code is required")
    if not normalized.isalnum():
        raise ValueError("promo code must be alphanumeric")
    if normalized not in ACTIVE_CODES:
        raise ValueError("promo code is not active")
    return normalized
''',
        ),
        (
            "cart_controller.py",
            '''    updated = dict(cart)
    updated["discount"] = promo_service.discount_for(code)
    updated["promo_code"] = code
    return updated
''',
            '''    normalized = promo_service.validate_promo(code)
    updated = dict(cart)
    updated["discount"] = promo_service.discount_for(normalized)
    updated["promo_code"] = normalized
    return updated
''',
        ),
    ),
    "L3_local_refactor_three_files": (
        (
            "parsing_utils.py",
            "",
            '''"""Shared string-parsing helpers for the fixture's related test files."""


def split_pair(text: str, sep: str) -> tuple[str, str]:
    """Split one key/value pair and drop surrounding quotes from the value."""
    key, _, value = text.partition(sep)
    return key.strip(), value.strip().strip('"')
''',
        ),
        (
            "tests/check_query_parsing.py",
            SHARED_SPLIT_PAIR,
            "from parsing_utils import split_pair as _split_pair\n",
        ),
        (
            "tests/check_header_parsing.py",
            SHARED_SPLIT_PAIR,
            "from parsing_utils import split_pair as _split_pair\n",
        ),
        (
            "tests/check_cookie_parsing.py",
            SHARED_SPLIT_PAIR,
            "from parsing_utils import split_pair as _split_pair\n",
        ),
    ),
    "L3_refactor_logger_four_files": (
        (
            "email_handler.py",
            '''    return json.dumps({"message": f"email handled {job['event']}"})
''',
            '''    return json.dumps(
        {"event": job["event"], "handler": HANDLER, "level": job.get("level", "info")},
        sort_keys=True,
    )
''',
        ),
        (
            "sms_handler.py",
            '''    return json.dumps({"channel": "sms", "job": job["event"]})
''',
            '''    return json.dumps(
        {"event": job["event"], "handler": HANDLER, "level": job.get("level", "info")},
        sort_keys=True,
    )
''',
        ),
        (
            "webhook_handler.py",
            '''    return json.dumps({"webhook_event": job["event"], "status": "ok"})
''',
            '''    return json.dumps(
        {"event": job["event"], "handler": HANDLER, "level": job.get("level", "info")},
        sort_keys=True,
    )
''',
        ),
        (
            "audit_handler.py",
            '''    return json.dumps(["audit", job["event"]])
''',
            '''    return json.dumps(
        {"event": job["event"], "handler": HANDLER, "level": job.get("level", "info")},
        sort_keys=True,
    )
''',
        ),
    ),
}

GOLD_CASES = tuple(case for case in CASES if case.level == "L3")
GOLD_CASE_IDS = [case.name for case in GOLD_CASES]


def apply_gold_fix(case_name: str, copy: Path) -> None:
    """Apply the embedded known-correct patch to one fixture copy (tmp only)."""
    for relpath, anchor, replacement in GOLD_FIXES[case_name]:
        target = copy / relpath
        if anchor == "":
            assert not target.exists(), f"creation step would clobber {target}"
            target.write_text(replacement, encoding="utf-8")
            continue
        text = target.read_text(encoding="utf-8")
        assert text.count(anchor) == 1, (
            f"gold-fix anchor for {case_name} must occur exactly once in "
            f"{relpath}, found {text.count(anchor)} occurrences"
        )
        target.write_text(text.replace(anchor, replacement), encoding="utf-8")


def run_fresh_copy(
    case: e2e_corpus.ExecutionCase, prefix: str, mutate=None
) -> tuple[int, dict[str, int], str]:
    """Run test_cmd from a fresh fixture copy, optionally mutating it first."""
    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        copy = Path(tmp) / "fixture"
        shutil.copytree(ROOT / case.fixture_dir, copy, symlinks=True)
        if mutate is not None:
            mutate(copy)
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


@lru_cache(maxsize=None)
def run_initial_state(case_name: str, attempt: int) -> tuple[int, dict[str, int], str]:
    """Run a case's frozen test_cmd from a fresh copy of its fixture.

    Cached per (case, attempt) so the launch test, the determinism test and
    the distinguishing test share runs: two fresh initial-state copies per
    case for the whole pytest session.
    """
    case = CASES_BY_NAME[case_name]
    return run_fresh_copy(case, prefix=f"exec-corpus-{case_name}-{attempt}-")


@lru_cache(maxsize=None)
def run_known_correct_state(case_name: str) -> tuple[int, dict[str, int], str]:
    """Run test_cmd on a fresh copy after applying the embedded known fix.

    Cached so repeated parametrizations share one patched run per case.
    """
    case = CASES_BY_NAME[case_name]
    return run_fresh_copy(
        case,
        prefix=f"exec-corpus-gold-{case_name}-",
        mutate=lambda copy: apply_gold_fix(case_name, copy),
    )


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


@pytest.mark.parametrize("case", GOLD_CASES, ids=GOLD_CASE_IDS)
def test_acceptance_distinguishes_initial_state_from_known_correct_patch(case):
    """The frozen acceptance test must separate the initial state from a
    known-correct local patch embedded in this file and applied only to a
    fresh tmp copy of the fixture (never to the committed fixture itself).
    """
    assert set(GOLD_FIXES) == set(GOLD_CASE_IDS), (
        "every L3 case needs an embedded known-correct patch; "
        f"patched={sorted(GOLD_FIXES)} expected={sorted(GOLD_CASE_IDS)}"
    )

    initial_code, initial_counts, initial_output = run_initial_state(case.name, 0)
    assert initial_code == 1 and initial_counts.get("failed", 0) >= 1, (
        f"initial state must fail the acceptance tests before the patch is "
        f"applied (exit {initial_code}, {initial_counts}):\n{initial_output[-2000:]}"
    )

    patched_code, patched_counts, patched_output = run_known_correct_state(case.name)
    assert patched_code == 0, (
        f"known-correct patch must make {case.test_cmd} pass "
        f"(exit status {patched_code}):\n{patched_output[-2000:]}"
    )
    assert patched_counts.get("failed", 0) == 0, (
        f"patched state must have no failing tests:\n{patched_output[-2000:]}"
    )
    assert patched_counts.get("error", 0) == 0, (
        f"patched state must have no test errors:\n{patched_output[-2000:]}"
    )
    assert patched_counts.get("passed", 0) >= 1, (
        f"patched state must actually run passing tests:\n{patched_output[-2000:]}"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

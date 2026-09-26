"""Meta-tests for the frozen L1-L5 execution-corpus fixture repositories.

Each fixture is a self-contained miniature repository whose frozen test command
must run locally, offline, and deterministically from a fresh copy. The tests
check fixture isolation/contract properties; for every L3-L5 case they also
prove the acceptance test distinguishes the initial state from a known-correct
patch (the distinguishing verification sanctioned for Task 3). Those patches
live only in this file and are applied to throwaway tmp copies — the committed
fixture directories stay unsolved, so a benchmark run never sees a solution.
The elevated/security L5 case additionally proves it runs fully offline against
a locally modeled provider. Parameterization is derived from the frozen
manifest, never hand-written, so fixture metadata cannot drift from
`cases.json`.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import e2e_corpus  # noqa: E402

MANIFEST_PATH = ROOT / "evals" / "execution_corpus" / "cases.json"
LEVELS_UNDER_TEST = ("L1", "L2", "L3", "L4", "L5")
GOLD_LEVELS = ("L3", "L4", "L5")
RUN_TIMEOUT_SECONDS = 120
EXPECTED_OUTCOME_PATTERN = re.compile(
    r"Expected initial test outcome:\s*(?P<label>[A-Z]+)\s*\(pytest exit status (?P<code>\d+)\)"
)
SUMMARY_COUNT_PATTERN = re.compile(r"(\d+) (passed|failed|error|skipped)")
NETWORK_IMPORT_PATTERN = re.compile(
    r"^[ \t]*(?:import|from)[ \t]+([A-Za-z_][\w.]*)", re.MULTILINE
)
# Fixtures must be fully offline and self-contained: any import below (or below
# one of its submodules) could reach the network, spawn a process, or load an
# unscannable dynamic module, so none of them may appear in fixture sources.
BANNED_SANDBOX_MODULES = (
    "aiohttp",
    "ctypes",
    "ftplib",
    "http",
    "importlib",
    "requests",
    "smtplib",
    "socket",
    "subprocess",
    "telnetlib",
    "urllib",
    "webbrowser",
)
# Non-.py escape hatch: a fixture config could inject plugins or CLI arguments
# that break the hermetic offline contract of the frozen test_cmd.
CONFIG_FILE_PATTERNS = ("*.ini", "*.cfg", "*.toml")
ADD_OPTS_PATTERN = re.compile(r"(?im)^[ \t]*addopts[ \t]*=")
# The elevated/security case must state its offline/mock-provider contract.
URL_PATTERN = re.compile(r"(?:https?|wss?|ftp)://")
# pytest itself is the fixture test runner; everything else must be stdlib or a
# fixture-local module.
THIRD_PARTY_ALLOWED_MODULES = frozenset({"pytest"})

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


def forbidden_imports(text: str) -> list[str]:
    """Banned sandbox-escape modules imported by one source file, sorted."""
    found = {
        module
        for module in NETWORK_IMPORT_PATTERN.findall(text)
        if any(
            module == banned or module.startswith(banned + ".")
            for banned in BANNED_SANDBOX_MODULES
        )
    }
    return sorted(found)


def classify(pytest_output: str) -> dict[str, int]:
    """Counts from the pytest summary line, ignoring timings and paths."""
    counts: dict[str, int] = {}
    for value, name in SUMMARY_COUNT_PATTERN.findall(pytest_output):
        counts[name] = int(value)
    return counts


def declared_outcome(case: e2e_corpus.ExecutionCase) -> re.Match:
    """The frozen README line declaring the case's initial-state outcome."""
    readme = fixture_root(case) / "README.md"
    assert readme.is_file(), f"{case.name} fixture must document its expected initial outcome"
    match = EXPECTED_OUTCOME_PATTERN.search(readme.read_text(encoding="utf-8"))
    assert match, f"{readme} must record 'Expected initial test outcome: ...'"
    return match


def assert_initial_precondition(
    case: e2e_corpus.ExecutionCase,
    match: re.Match,
    returncode: int,
    counts: dict[str, int],
    output: str,
) -> None:
    """The observed initial run must equal the README-declared precondition.

    `FAIL (pytest exit status 1)` is the normal declaration. A non-1
    declaration is only permitted when the frozen acceptance text itself allows
    a non-passing outcome other than a test failure ("fails or times out");
    without that backing, any case could weaken its precondition through the
    README line alone.
    """
    label = match.group("label")
    declared_code = int(match.group("code"))

    assert returncode == declared_code, (
        f"declared initial exit status {declared_code} != observed {returncode}\n"
        f"{output[-2000:]}"
    )

    if declared_code == 1:
        assert label == "FAIL", "initial state must exhibit the target defect"
        assert counts.get("failed", 0) >= 1, (
            f"initial state must fail the acceptance tests:\n{output[-2000:]}"
        )
        return

    assert re.search(r"fails or times out", case.acceptance, re.IGNORECASE), (
        f"{case.name} declares initial exit {declared_code}, but its frozen "
        "acceptance text does not allow a non-1 precondition ('fails or times out')"
    )
    assert label in ("FAIL", "ERROR", "TIMEOUT"), (
        f"{case.name}: unsupported non-1 precondition label {label!r}"
    )
    if counts:
        assert counts.get("failed", 0) + counts.get("error", 0) >= 1, (
            f"a declared non-1 precondition must still be a non-passing run:\n"
            f"{output[-2000:]}"
        )


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
# patch per L3-L5 case, embedded here (never under fixtures/) and applied only
# to fresh tmp copies. Each step is (relative path, anchor text, replacement);
# an empty anchor means "create this file with the given content", otherwise the
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
    "L4_public_api_change": (
        (
            "api.py",
            '''"""User-profile API still speaking the legacy data/error response envelope."""
from __future__ import annotations

USERS = {
    "u1": {"id": "u1", "name": "ada", "role": "admin"},
    "u2": {"id": "u2", "name": "lin", "role": "user"},
}


class Response:
    """One HTTP-ish response: status, JSON body, and content type."""

    def __init__(self, status: int, body: dict, content_type: str) -> None:
        self.status = status
        self.body = body
        self.content_type = content_type


def get_user(user_id: str) -> Response:
    """Return one user, or an error envelope when the id is unknown."""
    user = USERS.get(user_id)
    if user is None:
        return Response(
            404,
            {"data": None, "error": {"code": "not_found", "message": f"user {user_id} not found"}},
            "application/json",
        )
    return Response(200, {"data": user, "error": None}, "application/json")


def get_admin_settings(user_id: str) -> Response:
    """Return admin settings, or an error envelope for non-admin users."""
    user = USERS.get(user_id)
    if user is None:
        return Response(
            404,
            {"data": None, "error": {"code": "not_found", "message": f"user {user_id} not found"}},
            "application/json",
        )
    if user["role"] != "admin":
        return Response(
            403,
            {"data": None, "error": {"code": "forbidden", "message": "admin role required"}},
            "application/json",
        )
    return Response(200, {"data": {"theme": "dark", "retention_days": 30}, "error": None}, "application/json")
''',
            '''"""User-profile API speaking RFC7807 problem details on error responses."""
from __future__ import annotations

USERS = {
    "u1": {"id": "u1", "name": "ada", "role": "admin"},
    "u2": {"id": "u2", "name": "lin", "role": "user"},
}


class Response:
    """One HTTP-ish response: status, JSON body, and content type."""

    def __init__(self, status: int, body: dict, content_type: str) -> None:
        self.status = status
        self.body = body
        self.content_type = content_type


def problem_response(status: int, title: str, problem_type: str, detail: str) -> Response:
    """Build one RFC7807 problem+json error response."""
    return Response(
        status,
        {"type": problem_type, "title": title, "status": status, "detail": detail},
        "application/problem+json",
    )


def get_user(user_id: str) -> Response:
    """Return one user, or a problem response when the id is unknown."""
    user = USERS.get(user_id)
    if user is None:
        return problem_response(
            404, "Not Found", "/problems/not-found", f"user {user_id} not found"
        )
    return Response(200, dict(user), "application/json")


def get_admin_settings(user_id: str) -> Response:
    """Return admin settings, or a problem response for non-admin users."""
    user = USERS.get(user_id)
    if user is None:
        return problem_response(
            404, "Not Found", "/problems/not-found", f"user {user_id} not found"
        )
    if user["role"] != "admin":
        return problem_response(
            403, "Forbidden", "/problems/forbidden", "admin role required"
        )
    return Response(200, {"theme": "dark", "retention_days": 30}, "application/json")
''',
        ),
    ),
    "L4_cross_module_refactor": (
        (
            "core.py",
            '''"""Core helpers shared across the application (billing helpers live here too)."""
from __future__ import annotations


def slugify(text: str) -> str:
    """Lower-case and hyphenate a title."""
    return "-".join(text.lower().split())


def apply_tax(amount: float, rate: float) -> float:
    """Return amount plus tax at rate, rounded to cents."""
    return round(amount * (1 + rate), 2)


def format_invoice_total(invoice: dict) -> str:
    """Render an invoice total as a currency string."""
    return f"{invoice['currency']} {invoice['total']:.2f}"
''',
            '''"""Core helpers shared across the application."""
from __future__ import annotations


def slugify(text: str) -> str:
    """Lower-case and hyphenate a title."""
    return "-".join(text.lower().split())
''',
        ),
        (
            "billing.py",
            '''"""Billing domain values; the billing helpers have not moved here yet."""
from __future__ import annotations

INVOICE_PREFIX = "INV"
CURRENCY = "USD"
''',
            '''"""Billing domain values and the billing helpers moved from core."""
from __future__ import annotations

INVOICE_PREFIX = "INV"
CURRENCY = "USD"


def apply_tax(amount: float, rate: float) -> float:
    """Return amount plus tax at rate, rounded to cents."""
    return round(amount * (1 + rate), 2)


def format_invoice_total(invoice: dict) -> str:
    """Render an invoice total as a currency string."""
    return f"{invoice['currency']} {invoice['total']:.2f}"
''',
        ),
        (
            "orders.py",
            "from core import apply_tax, format_invoice_total",
            "from billing import apply_tax, format_invoice_total",
        ),
        (
            "accounts.py",
            "from core import apply_tax, format_invoice_total",
            "from billing import apply_tax, format_invoice_total",
        ),
    ),
    "L4_rename_type_across_ten_files": (
        ("models.py", "UserProfileDTO", "UserProfile"),
    )
    + tuple(
        (f"service_{index:02d}.py", "models.UserProfileDTO", "models.UserProfile")
        for index in range(1, 11)
    ),
    "L5_concurrency_race_condition": (
        (
            "thread_pool.py",
            '''                key, fn, args = self._queue.popleft()
                # NOTE: the freed queue slot is never announced to producers.
''',
            '''                key, fn, args = self._queue.popleft()
                self._not_full.notify()
''',
        ),
    ),
    "L5E_security_oauth_token_refresh": (
        (
            "jwt_tokens.py",
            '''    header, payload, signature = parts
    if not signature:
        raise ValueError("missing signature")
    return json.loads(_b64url_decode(payload))
''',
            '''    header, payload, signature = parts
    if not signature:
        raise ValueError("missing signature")
    decoded_header = json.loads(_b64url_decode(header))
    if decoded_header.get("alg") != HEADER["alg"]:
        raise ValueError("unsupported algorithm")
    signing_input = f"{header}.{payload}".encode("ascii")
    expected = hmac.new(secret, signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, _b64url_decode(signature)):
        raise ValueError("signature mismatch")
    return json.loads(_b64url_decode(payload))
''',
        ),
        (
            "oauth_provider.py",
            '''            access_token = jwt_tokens.sign(
                {"sub": client_id, "scope": "profile.read"}, SIGNING_SECRET
            )
            return {"access_token": access_token, "refresh_token": refresh_token}
''',
            '''            access_token = jwt_tokens.sign(
                {"sub": client_id, "scope": "profile.read"}, SIGNING_SECRET
            )
            self._revoked.add(refresh_token)
            self._serial += 1
            rotated = f"refresh-{self._serial:04d}"
            self._issued[rotated] = client_id
            return {"access_token": access_token, "refresh_token": rotated}
''',
        ),
    ),
    "L5_new_plugin_architecture": (
        (
            "plugin_loader.py",
            '''"""Dynamic plugin loader that executes every plugin against one shared context."""
''',
            '''"""Dynamic plugin loader that executes every plugin against an isolated context."""
''',
        ),
        (
            "plugin_loader.py",
            '''    loaded: dict[str, dict] = {}
    shared_context: dict = {}
    for path in sorted(Path(plugin_dir).glob("*.py")):
''',
            '''    loaded: dict[str, dict] = {}
    for path in sorted(Path(plugin_dir).glob("*.py")):
        plugin_context: dict = {}
''',
        ),
        (
            "plugin_loader.py",
            "        register(shared_context)\n",
            "        register(plugin_context)\n",
        ),
        (
            "plugin_loader.py",
            "        loaded[path.stem] = shared_context\n",
            "        loaded[path.stem] = plugin_context\n",
        ),
    ),
}

GOLD_CASES = tuple(case for case in CASES if case.level in GOLD_LEVELS)
GOLD_CASE_IDS = [case.name for case in GOLD_CASES]
SECURITY_CASES = tuple(case for case in CASES if case.tier == "elevated")
SECURITY_CASE_IDS = [case.name for case in SECURITY_CASES]


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
    """Run test_cmd from a fresh fixture copy, optionally mutating it first.

    A hung fixture must fail loudly as an assertion with its captured output
    instead of escaping as subprocess.TimeoutExpired (which pytest would report
    as an ERROR rather than a clean failure).
    """
    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        copy = Path(tmp) / "fixture"
        shutil.copytree(ROOT / case.fixture_dir, copy, symlinks=True)
        if mutate is not None:
            mutate(copy)
        try:
            process = subprocess.run(
                shlex.split(case.test_cmd),
                cwd=copy,
                env=subprocess_env(),
                capture_output=True,
                text=True,
                timeout=RUN_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            # POSIX capture_output+text hands TimeoutExpired BYTE parts; decode
            # them so the failure message carries the real captured output.
            captured = "".join(
                part.decode(errors="replace")
                if isinstance(part, bytes)
                else part
                for part in (exc.stdout, exc.stderr)
                if isinstance(part, (str, bytes))
            )
            raise AssertionError(
                f"{case.name}: {case.test_cmd} did not finish within "
                f"{RUN_TIMEOUT_SECONDS}s from a fresh fixture copy; "
                f"captured output:\n{captured[-2000:]}"
            ) from exc
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
def test_fixture_source_never_escapes_the_local_sandbox(case):
    """Static scan of every fixture source file.

    Goes beyond network client imports: process spawning (subprocess), FFI
    (ctypes) and dynamic imports (importlib) are escape hatches that could
    reach the network through an unscannable vector, so they are banned too.
    """
    root = fixture_root(case)
    offenders: dict[str, list[str]] = {}
    for path in sorted(root.rglob("*.py")):
        found = forbidden_imports(path.read_text(encoding="utf-8"))
        if found:
            offenders[str(path.relative_to(root))] = found

    assert offenders == {}, f"sandbox-escaping imports found in fixture: {offenders}"


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_fixture_configs_declare_no_addopts(case):
    """Non-.py escape hatch: addopts could inject plugins or CLI flags that
    break the hermetic, offline contract of the frozen test_cmd."""
    root = fixture_root(case)
    offenders: list[str] = []
    for pattern in CONFIG_FILE_PATTERNS:
        for path in sorted(root.rglob(pattern)):
            if ADD_OPTS_PATTERN.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(root)))

    assert offenders == [], f"fixture configs may not declare addopts: {offenders}"


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_test_command_launches_locally(case):
    match = declared_outcome(case)
    declared_code = int(match.group("code"))
    returncode, counts, output = run_initial_state(case.name, 0)

    assert returncode == declared_code, (
        f"{case.test_cmd} must reproduce the declared initial outcome against a "
        f"fresh fixture copy (expected exit {declared_code}, got {returncode}):\n"
        f"{output[-2000:]}"
    )
    if declared_code in (0, 1):
        assert counts, f"test_cmd produced no pytest summary:\n{output[-2000:]}"


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_initial_state_is_deterministic_across_fresh_copies(case):
    match = declared_outcome(case)

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

    assert_initial_precondition(case, match, first_code, first_counts, first_output)


@pytest.mark.parametrize("case", GOLD_CASES, ids=GOLD_CASE_IDS)
def test_acceptance_distinguishes_initial_state_from_known_correct_patch(case):
    """The frozen acceptance test must separate the initial state from a
    known-correct local patch embedded in this file and applied only to a
    fresh tmp copy of the fixture (never to the committed fixture itself).
    """
    assert set(GOLD_FIXES) == set(GOLD_CASE_IDS), (
        "every L3-L5 case needs an embedded known-correct patch; "
        f"patched={sorted(GOLD_FIXES)} expected={sorted(GOLD_CASE_IDS)}"
    )

    match = declared_outcome(case)
    initial_code, initial_counts, initial_output = run_initial_state(case.name, 0)
    assert_initial_precondition(case, match, initial_code, initial_counts, initial_output)

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


@pytest.mark.parametrize("case", SECURITY_CASES, ids=SECURITY_CASE_IDS)
def test_elevated_security_fixture_is_offline_and_models_rotation_locally(case):
    """Elevated/security tier contract.

    The fixture must need no live provider and no external network at all:
    only stdlib and fixture-local imports, no URL literals, an offline/mock
    README declaration, and the security-sensitive refresh/rotation behavior
    modeled locally under deterministic acceptance tests.
    """
    root = fixture_root(case)

    readme_text = (root / "README.md").read_text(encoding="utf-8").lower()
    for required in ("offline", "mock", "deterministic"):
        assert required in readme_text, (
            f"{case.name} README must document a fully offline, deterministic "
            f"run against a local mock provider (missing {required!r})"
        )

    local_modules = {path.stem for path in root.rglob("*.py")}
    python_parts: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.suffix not in {".py", ".ini", ".md"}:
            continue
        text = path.read_text(encoding="utf-8")
        url = URL_PATTERN.search(text)
        assert url is None, (
            f"{case.name} must reference no external endpoint, found {url.group(0)!r} "
            f"in {path.name}"
        )
        if path.suffix != ".py":
            continue
        python_parts.append(text)
        for module in NETWORK_IMPORT_PATTERN.findall(text):
            top = module.split(".")[0]
            assert (
                top in sys.stdlib_module_names
                or top in local_modules
                or top in THIRD_PARTY_ALLOWED_MODULES
            ), (
                f"{case.name} must run fully offline against local code only: "
                f"{path.name} imports {module!r}"
            )

    all_python = "\n".join(python_parts)
    assert "def refresh" in all_python, (
        f"{case.name} must locally model the refresh-token flow (def refresh ...)"
    )
    assert "rotat" in all_python.lower(), (
        f"{case.name} acceptance tests must exercise refresh-token rotation"
    )


def test_non_1_initial_precondition_needs_frozen_acceptance_backing():
    """A README may declare a non-1 initial exit status only when the frozen
    acceptance text itself allows an outcome other than exit-1 test failure."""
    declared_timeout = EXPECTED_OUTCOME_PATTERN.search(
        "Expected initial test outcome: TIMEOUT (pytest exit status 124)"
    )
    assert declared_timeout is not None
    declared_fail = EXPECTED_OUTCOME_PATTERN.search(
        "Expected initial test outcome: FAIL (pytest exit status 1)"
    )
    assert declared_fail is not None

    base = CASES_BY_NAME["L5_concurrency_race_condition"]
    allowed = replace(
        base, acceptance="Fixture test fails or times out on the initial state."
    )
    assert_initial_precondition(allowed, declared_timeout, 124, {}, "")

    denied = replace(
        base,
        acceptance="Fixture tests fail on the initial state and pass after the fix.",
    )
    with pytest.raises(AssertionError, match="fails or times out"):
        assert_initial_precondition(denied, declared_timeout, 124, {}, "")

    with pytest.raises(AssertionError, match="declared initial exit status"):
        assert_initial_precondition(denied, declared_fail, 5, {}, "")

    with pytest.raises(AssertionError, match="fail the acceptance tests"):
        assert_initial_precondition(denied, declared_fail, 1, {}, "")

    pass_label = EXPECTED_OUTCOME_PATTERN.search(
        "Expected initial test outcome: PASS (pytest exit status 124)"
    )
    with pytest.raises(AssertionError, match="non-1 precondition label"):
        assert_initial_precondition(allowed, pass_label, 124, {}, "")


def test_hung_fixture_command_fails_as_a_clean_failure(monkeypatch):
    """subprocess.TimeoutExpired must surface as an AssertionError carrying the
    captured output, not as an uncaught exception pytest would report as ERROR."""
    case = CASES_BY_NAME["L1_doc_typo_fix"]

    def hang(*args, **kwargs):
        # Real POSIX capture_output+text runs hand TimeoutExpired BYTE parts
        # (verified on darwin), so the handler must decode them.
        raise subprocess.TimeoutExpired(
            cmd="python3 -m pytest",
            timeout=1,
            output=b"partial stdout",
            stderr=b"partial stderr",
        )

    monkeypatch.setattr(subprocess, "run", hang)
    with pytest.raises(AssertionError, match="did not finish within") as excinfo:
        run_fresh_copy(case, prefix="exec-corpus-hung-")

    assert "partial stdout" in str(excinfo.value)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

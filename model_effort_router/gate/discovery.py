"""Test Gate command discovery (spec 15): config -> AGENTS.md/CLAUDE.md -> CI files -> manifests.

Only simple commands (no shell operators or globs) are taken from repo prose/CI/manifests; a check nobody
declared stays None and is reported `not_run`, never passed.
"""

import json
import re
from collections import namedtuple
from pathlib import Path

KINDS = ("test", "lint", "typecheck", "build")
Check = namedtuple("Check", "kind command source shell")

_PY = r"(?:python3?|py)"
_PATTERNS = {
    "test": r"(?:{py} -m (?:unittest|pytest)|pytest|npm (?:run )?test|yarn test|pnpm (?:run )?test|"
    r"go test|cargo test|make test|bundle exec rspec|mvn test|gradle test)\b",
    "lint": r"(?:ruff\b|flake8|pylint|eslint|npm run lint|yarn lint|pnpm (?:run )?lint|make lint|"
    r"golangci-lint|cargo clippy|{py} -m (?:ruff|flake8|pylint))",
    "typecheck": r"(?:mypy|pyright|tsc\b|npm run (?:typecheck|type-check)|yarn typecheck|"
    r"pnpm (?:run )?typecheck|make typecheck|cargo check|{py} -m (?:mypy|pyright))",
    "build": r"(?:npm run build|yarn build|pnpm (?:run )?build|make build|cargo build|go build)",
}
_PATTERNS = {k: re.compile("^" + v.replace("{py}", _PY)) for k, v in _PATTERNS.items()}
_UNSAFE = re.compile(r"[&|;<>$`()*?\[\]{}]")  # shell operators and globs
_FENCE = re.compile(r"^\s*```")
_CI_FILES = (".gitlab-ci.yml", ".travis.yml")


def classify(line):
    """(kind, cleaned_line) for a single simple command line; (None, line) if it matches no kind; None if unusable."""
    line = re.sub(r"\s+#.*$", "", line.strip().lstrip("$ ").strip())
    if not line or _UNSAFE.search(line):
        return None
    return next((k for k in KINDS if _PATTERNS[k].match(line)), None), line


def _scan(lines):
    found = {}
    for raw in lines:
        kind, line = classify(raw) or (None, None)
        if kind and kind not in found:
            found[kind] = line
    return found


def _docs_candidates(text):
    in_fence = False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        elif in_fence:  # fenced blocks only: inline backticks in prose are too ambiguous
            yield line


def _ci_candidates(text):
    for line in text.splitlines():
        line = line.strip().lstrip("- ").strip()
        yield re.sub(r"^run:\s*", "", line)


def _read(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _from_files(root, names, candidates):
    found = {}
    for name in names:
        for kind, cmd in _scan(candidates(_read(root / name))).items():
            found.setdefault(kind, (cmd, name))
    return found


def _ci_names(root):
    wf = sorted(p.relative_to(root).as_posix() for p in (root / ".github/workflows").glob("*.y*ml"))
    return wf + [n for n in _CI_FILES if (root / n).exists()]


def _package_json(root):
    try:
        scripts = json.loads(_read(root / "package.json")).get("scripts", {})
    except (ValueError, AttributeError):
        return {}
    if not isinstance(scripts, dict):
        return {}
    out = {}
    test = scripts.get("test")
    if isinstance(test, str) and "no test specified" not in test:
        out["test"] = "npm test"
    for kind, names in (("lint", ("lint",)), ("typecheck", ("typecheck", "type-check")), ("build", ("build",))):
        name = next((n for n in names if n in scripts), None)
        if name:
            out[kind] = f"npm run {name}"
    return out


def _pyproject(root):
    text = _read(root / "pyproject.toml")
    return {
        k: c
        for k, marker, c in (
            ("test", "[tool.pytest", "python3 -m pytest"),
            ("lint", "[tool.ruff", "ruff check ."),
            ("typecheck", "[tool.mypy", "mypy ."),
        )
        if marker in text
    }


def _makefile(root):
    text = _read(root / "Makefile")
    return {k: f"make {k}" for k in KINDS if re.search(rf"^{k}\s*:", text, re.M)}


def _validate_config(config):
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise ValueError("gate.checks must be an object")
    for kind, cmd in config.items():
        if kind not in KINDS:
            raise ValueError(f"gate.checks: unknown check {kind!r}; expected one of {KINDS}")
        if not isinstance(cmd, str) or not cmd.strip():
            raise ValueError(f"gate.checks.{kind} must be a non-empty string")
    return config


def discover(root, config=None):
    """{kind: Check or None} for every kind in KINDS; highest-precedence source wins per kind."""
    root = Path(root)
    sources = [
        ("config", {k: (c, "config") for k, c in _validate_config(config).items()}),
        ("docs", _from_files(root, ("AGENTS.md", "CLAUDE.md"), _docs_candidates)),
        ("ci", _from_files(root, _ci_names(root), _ci_candidates)),
        *(
            (name, {k: (c, name) for k, c in fn(root).items()})
            for name, fn in (("package.json", _package_json), ("pyproject.toml", _pyproject), ("Makefile", _makefile))
        ),
    ]
    out = {}
    for kind in KINDS:
        hit = next((s[kind] for _, s in sources if kind in s), None)
        out[kind] = Check(kind, hit[0], hit[1], hit[1] == "config") if hit else None
    return out

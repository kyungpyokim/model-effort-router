#!/usr/bin/env python3
"""Session route reuse: follow-up tasks keep the stored classification instead of paying for a new one.

A caller names a session (``--session`` / MODEL_EFFORT_ROUTER_SESSION). The first task is classified
and stored; a later task in the same session and workspace reuses that classification (no classifier
call) unless a deterministic blocker fires: workspace changed, stored route expired, an earlier run
re-planned or gave up, or the new task text shows a different operation, wider scope, or new risk
evidence. Blockers are conservative keyword checks (English and Korean); unknown means reuse.

This module is dependency-free on purpose: it only moves plain dicts.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import stat
import tempfile
import time
from pathlib import Path

REUSE_TTL_SECONDS = 4 * 3600
MAX_REUSES = 10
MAX_RECORD_BYTES = 65536
STATE_DIR_ENV = "MODEL_EFFORT_ROUTER_STATE_DIR"
SESSION_ENV = "MODEL_EFFORT_ROUTER_SESSION"
RECORD_VERSION = 1

_EN_MODIFY = "fix|implement|add|change|update|refactor|rename|remove|delete|create|write|build|patch"
_KO_MODIFY = "수정|구현|추가|변경|리팩터|리팩토링|삭제|만들|고치|고쳐|작성|개선|적용|교체|제거|바꿔|바꾸"
_EN_INSPECT = "review|explain|why|what|how|investigate|analy[sz]e|check|audit|design|plan"
_KO_INSPECT = "리뷰|설명|왜|어떻게|분석|확인|검토|설계"


def _words(english: str, korean: str) -> re.Pattern:
    """English stems match whole words (with a plain ending), so `address` is not `add`; Korean matches anywhere."""
    return re.compile(rf"\b(?:{english})(?:e?s|e?d|ing)?\b|(?:{korean})", re.IGNORECASE)


MODIFY_RE = _words(_EN_MODIFY, _KO_MODIFY)
INSPECT_RE = _words(_EN_INSPECT, _KO_INSPECT)
# Risk vocabulary per dimension. A miss fails unsafe (the stored low route is reused), so these
# lists are deliberately broad; false hits only cost one extra classification.
SECURITY_RE = re.compile(
    r"auth|login|password|passwd|token|secret|credential|crypto|encrypt|\bhash|payment|billing|refund|stripe|subscription|invoice"
    r"|permission|privilege|escalat|rbac|\bacl\b|tenant|\bpii\b|\bgdpr\b|injection|\bxss\b|\bcsrf\b|\bcors\b|\bjwt\b|oauth|\bsso\b"
    r"|cookie|session|\badmin\b|\brole\b|vulnerab|인증|권한|결제|비밀번호|토큰|암호|시크릿|개인정보|세션|쿠키|관리자|취약점|보안",
    re.IGNORECASE,
)
DATA_RE = re.compile(
    r"migrat|drop table|delete from|truncate|purge|\bprod(?:uction)?\b|deploy|ledger|\bschema\b|마이그레이션|운영|배포|스키마",
    re.IGNORECASE,
)
API_RE = re.compile(r"breaking change|public api|api contract|공개 ?api", re.IGNORECASE)
SECURITY_FLAGS = ("security_sensitive", "authentication", "authorization", "payment")
SCOPE_RE = re.compile(
    r"\bentire\b|\bwhole\b|\ball (?:the )?(?:files|modules|services|tests)\b|\bacross\b|\beverywhere\b|\bevery\b|\bthroughout\b|\brewrite\b|\bredesign\b"
    r"|전체|모든|전면|전부|재설계|아키텍처",
    re.IGNORECASE,
)


def state_dir() -> Path:
    return Path(os.environ.get(STATE_DIR_ENV) or Path.home() / ".cache" / "model-effort-router")


def record_path(session: str) -> Path:
    return state_dir() / f"session-{hashlib.sha256(session.encode('utf-8')).hexdigest()[:24]}.json"


def workspace_key(cwd: str) -> str:
    return str(Path(cwd).resolve())


def operation(text: str) -> str | None:
    """modify / inspect / mixed, or None when the text names no operation."""
    modify, inspect = bool(MODIFY_RE.search(text)), bool(INSPECT_RE.search(text))
    if modify and inspect:
        return "mixed"
    return "modify" if modify else "inspect" if inspect else None


def reuse_blockers(
    record: dict, cwd: str, task: str, code_change: bool, now: float | None = None, explicit_task_type: str | None = None,
) -> list[str]:
    """Reasons the stored route must not be reused for this task (empty means reuse it).

    Raises TypeError/ValueError/AttributeError on a malformed record; callers treat that as "reclassify"."""
    now = time.time() if now is None else now
    blockers = []
    if record.get("workspace") != workspace_key(cwd):
        blockers.append("workspace changed")
    age = now - record["saved_at"]
    if not 0 <= age <= REUSE_TTL_SECONDS:
        blockers.append("stored route expired")
    if record.get("reuses", 0) >= MAX_REUSES:
        blockers.append(f"reused {MAX_REUSES} times already")
    if record.get("blocked"):
        blockers.append(f"an earlier run invalidated it ({record['blocked']})")
    if record.get("unresolved"):
        blockers.append("the stored route still had unresolved facts")
    if explicit_task_type and explicit_task_type != record["task_type"]:
        blockers.append("task type pinned differently")
    op = operation(task)
    if op == "mixed":
        blockers.append("task mixes inspecting and modifying")
    elif op is None and not code_change:
        blockers.append("operation unclear for a read-only route")
    elif op is not None and op != ("modify" if code_change else "inspect"):
        blockers.append(f"operation changed to {op}")
    if SCOPE_RE.search(task):
        blockers.append("scope growth")
    flags = record["risk_flags"]
    if not isinstance(flags, dict):
        raise TypeError("risk_flags must be a mapping")
    covered = {
        "security": any(flags.get(flag) for flag in SECURITY_FLAGS),
        "data": bool(flags.get("data_migration")) or record.get("risk_tier") == "critical",
        "api": bool(flags.get("public_api_change")),
    }
    for name, pattern in (("security", SECURITY_RE), ("data", DATA_RE), ("api", API_RE)):
        if pattern.search(task) and not covered[name]:
            blockers.append(f"new {name} risk evidence")
    return blockers


def load_record(session: str) -> dict | None:
    """The session's record, or None when it is missing, foreign, a symlink, oversized, or unparsable."""
    path = record_path(session)
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_size > MAX_RECORD_BYTES:
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return record if isinstance(record, dict) and record.get("version") == RECORD_VERSION else None


def _write_record(session: str, record: dict) -> None:
    """Atomic private write: a temp file in the same directory, then rename (never follows a planted symlink)."""
    path = record_path(session)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".session-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream)
        os.replace(temp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp)
        raise


def save_record(session: str, cwd: str, classification: dict, saved_at: float | None = None, reuses: int = 0) -> None:
    """Store the classification for later tasks; a reused record keeps its original ``saved_at`` so the TTL bounds the chain."""
    _write_record(session, {
        "version": RECORD_VERSION,
        "workspace": workspace_key(cwd),
        "saved_at": time.time() if saved_at is None else saved_at,
        "reuses": reuses,
        "blocked": None,
        **classification,
    })


def mark_outcome(session: str, replans: int, exit_code: int) -> None:
    """A run that re-planned or failed shows the approved route did not hold: the next task reclassifies."""
    record = load_record(session)
    if record is None or not (replans or exit_code):
        return
    record["blocked"] = "re-planned" if replans else f"exit {exit_code}"
    _write_record(session, record)

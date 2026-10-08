"""Rule-based risk_flags detection. Always runs, independent of the backend (spec 7)."""

import re

from .decision import RISK_FLAGS

_PATTERNS = {
    "security": r"\bsecurity|\bvulnerab|\bxss\b|\bcsrf\b|\bsql injection|\bencrypt|\bcrypto|\bsecrets?\b|\bcve\b|보안",
    "auth": r"\bauth(?:n|z|enticat\w*|oriz\w*)?\b|\boauth|\blogin\b|\blogout\b|\bpasswords?\b"
    r"|\bjwt\b|\bsession tokens?\b|\bpermissions?\b|\bcredentials?\b|인증|로그인|권한",
    "payment": r"\bpayments?\b|\bbilling\b|\bcheckout\b|\binvoices?\b|\bstripe\b|\brefunds?\b|\bcharges?\b|결제",
    "data_migration": r"\bmigrat\w*|\bschema change|\balter table|마이그레이션",
    "data_loss": r"\bdata loss|\bdrop table|\btruncate\b|\bpurge\b|\bdelete all\b|\birreversible|데이터 손실|\brm -rf",
    "concurrency": r"\bconcurren\w*|\brace conditions?\b|\bdeadlock|\bmutex|\block(?:s|ing)?\b"
    r"|\bthreads?\b|\bthread-safe|동시성|경쟁 상태",
}
_COMPILED = {flag: re.compile(p, re.IGNORECASE) for flag, p in _PATTERNS.items()}
# Statements in code a run added. Only those: the request words above ("lock", "charge") are everywhere in code.
_CONTENT_PATTERNS = {
    "data_migration": r"\balter\s+table\b",
    "data_loss": r"\bdrop\s+(?:table|column|database|schema)\b|\btruncate\s+table\b|\brm\s+-rf\b",
}
_CONTENT_COMPILED = {flag: re.compile(p, re.IGNORECASE) for flag, p in _CONTENT_PATTERNS.items()}
_PATH_SEPARATORS = re.compile(r"[_\-./\\]+")


def detect_risk_flags(text, paths=()):
    # Path separators become spaces so "user_auth.py" and "db/migrations/" match word rules.
    haystack = " ".join([text or "", *(_PATH_SEPARATORS.sub(" ", p) for p in paths or ())])
    return tuple(flag for flag in RISK_FLAGS if _COMPILED[flag].search(haystack))


def detect_content_flags(text):
    return tuple(flag for flag in RISK_FLAGS if flag in _CONTENT_COMPILED and _CONTENT_COMPILED[flag].search(text))

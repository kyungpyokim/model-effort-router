"""Per-session rolling summary (state dir, next to the route log) and the context text handed to the classifier."""

import fcntl
import hashlib
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass

from ..logging import route_log
from .transcripts import clip

REFRESH_MIN_CHARS = 1500  # less new text than this stays raw in "Recent turns"; no summarizer call for it
PER_TURN_CHARS = 1500
MIN_PARTIAL_CHARS = 200
ANCHOR_TURNS = 2
RETENTION_S = 14 * 86400
LABELS = {"user": "User", "assistant": "Assistant"}


@dataclass(frozen=True)
class Stored:
    summary: str = ""
    anchor: tuple = ()  # digests of the last (up to) two turns folded into `summary`


def digest(turn):
    return hashlib.sha256(f"{turn.role}\0{turn.text}".encode("utf-8")).hexdigest()[:16]


def anchor_at(turns, end):
    """Anchor for "turns[:end] are covered". Two digests, so a repeated message ("진행") cannot match the wrong place."""
    return tuple(digest(t) for t in turns[max(0, end - ANCHOR_TURNS) : end])


def _sibling(sdir, session_id, suffix):
    return route_log.log_path(sdir, session_id)[: -len(".log.jsonl")] + suffix


def summary_path(sdir, session_id):
    return _sibling(sdir, session_id, ".summary.json")


def lock_path(sdir, session_id):
    return _sibling(sdir, session_id, ".summary.lock")


def load(sdir, session_id):
    try:
        with open(summary_path(sdir, session_id), encoding="utf-8") as f:
            data = json.load(f)
        text, anchor = data["summary"], data["anchor"]
        if (
            isinstance(text, str)
            and isinstance(anchor, list)
            and len(anchor) <= ANCHOR_TURNS
            and all(isinstance(a, str) for a in anchor)
        ):
            return Stored(text, tuple(anchor))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return Stored()


def save(sdir, session_id, text, anchor):
    """Atomic replace; private (0600) because it holds conversation content."""
    os.makedirs(sdir, mode=0o700, exist_ok=True)
    path = summary_path(sdir, session_id)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
            json.dump(
                {"summary": text, "anchor": list(anchor), "updated_at": round(time.time(), 3)}, f, ensure_ascii=False
            )
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@contextmanager
def locked(sdir, session_id):
    """Non-blocking exclusive lock; yields False when another refresh holds it. Released with the fd, so a crash frees it."""
    os.makedirs(sdir, mode=0o700, exist_ok=True)
    fd = os.open(lock_path(sdir, session_id), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            got = True
        except OSError:
            got = False
        yield got
    finally:
        os.close(fd)


def prune(sdir, keep=(), max_age_s=RETENTION_S):
    """Deletes summary and lock files untouched for `max_age_s` (never those in `keep`): old sessions leave no residue."""
    try:
        names = os.listdir(sdir)
    except OSError:
        return
    cutoff = time.time() - max_age_s
    for name in names:
        path = os.path.join(sdir, name)
        if ".summary." in name and name.endswith((".json", ".lock", ".tmp")) and path not in keep:
            try:
                if os.stat(path).st_mtime < cutoff:
                    os.unlink(path)
            except OSError:
                pass


def pending(turns, stored):
    """(summary to build on, turns it does not cover yet, index where those start). The anchor is searched backwards in
    `turns` (a window of the transcript, which may start mid-session). Not found: every turn is pending but the stored
    summary is still the base, so it is never lost."""
    anchor = stored.anchor
    if anchor:
        for i in range(len(turns) - 1, len(anchor) - 2, -1):
            if anchor_at(turns, i + 1)[-len(anchor) :] == anchor:
                return stored.summary, turns[i + 1 :], i + 1
    return stored.summary, turns, 0


def needs_refresh(turns, stored, min_chars=REFRESH_MIN_CHARS):
    _, fresh, _ = pending(turns, stored)
    return sum(len(t.text) for t in fresh) >= min_chars


def render(turn, limit=PER_TURN_CHARS):
    return f"{LABELS[turn.role]}: {clip(turn.text, limit)}"


def build_context(base, fresh, max_chars):
    """Summary plus the turns it does not cover (see `pending`), newest kept. "" when there is nothing yet. The current
    prompt is the task, so callers drop it from `fresh`."""
    if not base and not fresh:
        return ""
    head = f"Session summary:\n{clip(base, max_chars // 2) or '(none)'}\n\nRecent turns:\n"
    budget, lines = max_chars - len(head), []
    for turn in reversed(fresh):
        line, sep = render(turn), 1 if lines else 0
        if len(line) + sep > budget:
            if budget - sep >= MIN_PARTIAL_CHARS:
                lines.append(clip(line, budget - sep))
            break
        lines.append(line)
        budget -= len(line) + sep
    return head + ("\n".join(reversed(lines)) or "(none)")

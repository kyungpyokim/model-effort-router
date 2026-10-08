"""Main agent's current model, read from the host payload. None means unknown (callers keep the legacy advice).
Live-verified (Claude Code 2.1.285, interactive): SessionStart carries `model` and PostModelSwitch carries `to_model`,
both stored per session, so the first prompt (no transcript yet) and the prompt right after `/model` (transcript rows
may land late) are known. A "switch" value is authoritative until a transcript reply newer than it appears; a
"start" value only fills in when the transcript has no evidence. `claude -p` sends neither and stays unknown; `--resume --model X` may be covered by PostModelSwitch
(source "resume"), unverified."""

import contextlib
import json
import os
import re
import time
from datetime import datetime

from ..context.transcripts import _lines
from ..logging import route_log

TAIL_BYTES = 512 * 1024  # a model switch or the latest reply sits near the end; never read a huge transcript whole
_CONTEXT_SUFFIX = re.compile(r"\[[^\]]*\]$")  # e.g. "claude-sonnet-5-5[1m]"
_SNAPSHOT_SUFFIX = re.compile(r"-\d{8}$")  # e.g. "claude-haiku-4-5-20251001": the same model, dated snapshot name
_SWITCH_PREFIX = "<local-command-stdout>Set model to"
_SOURCES = ("start", "switch")
_NEEDLES = ('"assistant"', '"modelId"', "Set model to")


def normalize(model):
    """Lowercase, no whitespace, no context-window suffix; None for anything that is not a usable name."""
    if not isinstance(model, str):
        return None
    name = _SNAPSHOT_SUFFIX.sub("", _CONTEXT_SUFFIX.sub("", re.sub(r"\s+", "", model.lower())))
    return name if name and not name.startswith("<") else None  # "<synthetic>" is not a model


def _claude_row_model(row):
    if row.get("isSidechain"):
        return None
    if row.get("type") == "assistant":
        message = row.get("message")
        return message.get("model") if isinstance(message, dict) else None
    attachment = row.get("attachment")
    if row.get("type") == "attachment" and isinstance(attachment, dict) and attachment.get("type") == "model":
        identity = attachment.get("identity")
        return identity.get("modelId") if isinstance(identity, dict) else None
    return None


def _is_model_switch(row):
    """The `/model` command's stdout row; a row that merely quotes the text (a reply, a tool result) is not one.
    Seen as a `user` row with string `message.content` (interactive sessions, 17 rows across 2.1.219-2.1.293) and as a
    `system`/`local_command` row with top-level `content` (`claude -p`, 2.1.285)."""
    if row.get("isSidechain"):
        return False
    if row.get("type") == "system" and row.get("subtype") == "local_command":
        content = row.get("content")
    elif row.get("type") == "user":
        message = row.get("message")
        content = message.get("content") if isinstance(message, dict) else None
    else:
        return False
    return isinstance(content, str) and content.startswith(_SWITCH_PREFIX)


def _epoch(stamp):
    """Epoch seconds of an ISO row timestamp ("2026-10-08T14:41:25.490Z"); None when absent or unparsable."""
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def _claude(path):
    """(model, switched, epoch) from the transcript tail: the last assistant reply or model attachment (first
    turn/switch) with its timestamp, and whether a later "Set model to" row exists. The transcript format is private to Claude Code, so any surprise yields None."""
    found = at = None
    switched = False  # a "Set model to" row newer than the last model evidence
    try:
        for line in _lines(path, TAIL_BYTES):
            if not any(n in line for n in _NEEDLES):
                continue
            try:
                row = json.loads(line)
            except (ValueError, RecursionError):
                continue
            if not isinstance(row, dict):
                continue
            if _is_model_switch(row):
                switched = True
                continue
            model = normalize(_claude_row_model(row))
            if model:
                found, switched, at = model, False, _epoch(row.get("timestamp"))
    except OSError:
        pass
    return found, switched, at


def _session_model_path(sdir, session_id):
    return route_log.log_path(sdir, session_id)[: -len(".log.jsonl")] + ".model"  # same safe naming as the log


def save_session_model(sdir, session_id, model, source="start"):
    """Store the model name and where it came from ("start" or "switch"); an unusable one removes the stored value."""
    path = _session_model_path(sdir, session_id)
    name = normalize(model)
    if name is None:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(path)
        return
    os.makedirs(sdir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"model": name, "source": source, "ts": time.time()}, f)


def _stored_model(sdir, session_id):
    """(model, source, ts) or (None, None, None); an unknown source invalidates the value."""
    try:
        with open(_session_model_path(sdir, session_id), encoding="utf-8") as f:
            stored = json.load(f)
        source = stored["source"]
        if source not in _SOURCES:
            return None, None, None
        return normalize(stored["model"]), source, stored.get("ts")
    except (OSError, ValueError, KeyError, TypeError):
        return None, None, None


def main_model(data, host_name, sdir=None):
    if host_name == "codex":
        return normalize(data.get("model"))
    if host_name == "claude":
        stored, source, ts = _stored_model(sdir, data.get("session_id")) if sdir else (None, None, None)
        found, switched, at = _claude(data.get("transcript_path"))
        if stored and source == "switch" and not (found and at and isinstance(ts, (int, float)) and at > ts):
            return stored  # PostModelSwitch tracks every switch; only a reply written after it can outdate the value
        if found or switched:  # transcript evidence, even a pending switch, beats a start value
            return None if switched else found
        return stored
    return None

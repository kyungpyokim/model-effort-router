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
from collections import namedtuple
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


def _codex_model(data, sdir):
    return normalize(data.get("model"))


def _claude_model(data, sdir):
    stored, source, ts = _stored_model(sdir, data.get("session_id")) if sdir else (None, None, None)
    found, switched, at = _claude(data.get("transcript_path"))
    if stored and source == "switch" and not (found and at and isinstance(ts, (int, float)) and at > ts):
        return stored  # PostModelSwitch tracks every switch; only a reply written after it can outdate the value
    if found or switched:  # transcript evidence, even a pending switch, beats a start value
        return None if switched else found
    return stored


def _claude_effort(data, sdir):
    """Effort of Main's last reply, from the Claude transcript's assistant rows (`effort`). It is the previous turn's
    value: a change since then shows after the next reply. Not `$CLAUDE_EFFORT` or a payload `effort`: live-checked
    (`claude -p`), UserPromptSubmit gets neither, and the variable would only be inherited from a parent session."""
    found = None
    try:
        for line in _lines(data.get("transcript_path"), TAIL_BYTES):
            if '"assistant"' not in line:
                continue
            try:
                row = json.loads(line)
            except (ValueError, RecursionError):
                continue
            effort = row.get("effort") if isinstance(row, dict) and not row.get("isSidechain") else None
            if isinstance(effort, str) and effort:
                found = effort
    except OSError:
        pass
    return found


def _antigravity(path):
    """(model, effort) read from the latest settings change in the Antigravity transcript."""
    if not path:
        return None, None
    found_model, found_effort = None, None
    try:
        for line in _lines(path, TAIL_BYTES):
            if "Model Selection" not in line and "USER_SETTINGS_CHANGE" not in line:
                continue
            try:
                row = json.loads(line)
            except (ValueError, RecursionError):
                continue
            if not isinstance(row, dict):
                continue
            content = row.get("content")
            if not isinstance(content, str):
                continue
            match = _ANTIGRAVITY_SETTING.search(content)
            if match:
                raw_model = match.group(1).strip()
                model_str = re.sub(r"\s+", "-", raw_model).lower()
                model_str = model_str.replace("claude-sonnet-5.5", "claude-sonnet-5-5").replace(
                    "claude-opus-5.5", "claude-opus-5-5"
                )
                found_model = normalize(model_str)
                effort = match.group(2).strip().lower() if match.group(2) else None
                found_effort = effort if effort in ("low", "medium", "high", "xhigh") else None
    except OSError:
        pass
    return found_model, found_effort


def _antigravity_model(data, sdir):
    path = data.get("transcriptPath") or data.get("transcript_path")
    return _antigravity(path)[0]


def _antigravity_effort(data, sdir):
    path = data.get("transcriptPath") or data.get("transcript_path")
    return _antigravity(path)[1]


def _unknown(data, sdir):
    return None


_ANTIGRAVITY_SETTING = re.compile(
    r"`Model Selection`\s+(?:from\s+.*?\s+)?to\s+([A-Za-z0-9\s._-]+?)(?:\s*\(([^)\n]+)\))?\s*\.(?:\s*(?:No need to comment|</USER_SETTINGS_CHANGE>)|$)",
    re.IGNORECASE | re.MULTILINE,
)

# What each host's payload can tell about Main; a host without a reader (or a field) stays unknown.
MainReader = namedtuple("MainReader", "model effort")
READERS = {
    "claude": MainReader(_claude_model, _claude_effort),
    "codex": MainReader(_codex_model, _unknown),  # Codex payloads carry the model but no effort
    "antigravity": MainReader(_antigravity_model, _antigravity_effort),
}
_NO_READER = MainReader(_unknown, _unknown)


def main_model(data, host_name, sdir=None):
    return READERS.get(host_name, _NO_READER).model(data, sdir)


def main_effort(data, host_name):
    return READERS.get(host_name, _NO_READER).effort(data, None)

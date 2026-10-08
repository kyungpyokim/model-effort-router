"""Main agent's current model, read from the host payload. None means unknown (callers keep the legacy advice).
Live-verified limits (Claude Code 2.1.285): a new session's transcript does not exist yet on the first prompt (unknown);
the model attachment of a turn is written after the hook runs, so a `/model` switch is seen only through its
"Set model to" row (unknown until the next reply), and a `--resume --model X` launch still reads the previous model."""

import json
import re

from ..context.transcripts import _lines

TAIL_BYTES = 512 * 1024  # a model switch or the latest reply sits near the end; never read a huge transcript whole
_CONTEXT_SUFFIX = re.compile(r"\[[^\]]*\]$")  # e.g. "claude-sonnet-5-5[1m]"
_SNAPSHOT_SUFFIX = re.compile(r"-\d{8}$")  # e.g. "claude-haiku-4-5-20251001": the same model, dated snapshot name
_SWITCH_PREFIX = "<local-command-stdout>Set model to"
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


def _claude(path):
    """Last main-thread model in the transcript tail: an assistant reply, or a model attachment (first turn/switch).
    The transcript format is private to Claude Code, so any surprise yields None."""
    found = None
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
                found, switched = model, False
    except OSError:
        pass
    return None if switched else found


def main_model(data, host_name):
    if host_name == "codex":
        return normalize(data.get("model"))
    if host_name == "claude":
        return _claude(data.get("transcript_path"))
    return None

"""Host transcript file -> ordered (role, text) turns. User and assistant text only: tool calls and results, reasoning,
attachments and host-injected messages never reach a classifier or summarizer. Tolerates malformed lines and refuses
anything that is not a plain regular file (symlink, FIFO, directory)."""
import json
import os
import re
import stat
from collections import namedtuple

Turn = namedtuple("Turn", "role text")
# Messages the host itself puts in the user turn (a subagent's report, a background-task notice, a `!` shell
# command and its output, a slash-command echo): not the user's request, so never classified (no backend call).
HARNESS_MESSAGE = re.compile(
    r"\s*(?:Another Claude session sent a message:\s*)?(?:\[SYSTEM NOTIFICATION[^\]]*\]\s*)?"
    r"<(?:agent-message|cross-session-message|task-notification|bash-input|bash-stdout|bash-stderr"
    r"|local-command-stdout|local-command-caveat|command-name)\b")
SYSTEM_REMINDER = re.compile(r"<system-reminder>.*?(?:</system-reminder>|\Z)", re.DOTALL)  # anywhere in the text, even unclosed
CODEX_INJECTED = re.compile(r"\s*(?:# AGENTS\.md instructions\b|<[a-z]+(?:_[a-z]+)+[ >])")  # instructions, <environment_context>, ...
MAX_TURN_CHARS = 4000
MAX_READ_BYTES = 16 * 1024 * 1024  # ponytail: a larger file is read from its tail, so turn counts drift; page by offset if that bites


def clip(text, limit):
    """Head and tail of `text` within `limit` characters: a plan's opening and its closing question both matter."""
    if len(text) <= limit:
        return text
    head = limit * 3 // 4
    return text[:head] + "…" + text[len(text) - (limit - head - 1):]


def _texts(content, kinds):
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [b["text"] for b in content if isinstance(b, dict) and b.get("type") in kinds and isinstance(b.get("text"), str)]
    return []


def _turn(role, texts, injected=None):
    if role == "user":
        texts = [SYSTEM_REMINDER.sub("", t) for t in texts if not HARNESS_MESSAGE.match(t) and not (injected and injected.match(t))]
    text = "\n".join(t for t in texts if t.strip()).strip()
    return Turn(role, clip(text, MAX_TURN_CHARS)) if text else None


def _claude(row):
    role = row.get("type")
    message = row.get("message")
    if role not in ("user", "assistant") or row.get("isMeta") or row.get("isSidechain") or not isinstance(message, dict):
        return None
    if row.get("isCompactSummary"):  # the host's own compaction summary: context, not something the user said
        role = "assistant"
    return _turn(role, _texts(message.get("content"), ("text",)))


def _codex(row):
    payload = row.get("payload")
    if row.get("type") != "response_item" or not isinstance(payload, dict) or payload.get("type") != "message":
        return None
    role = payload.get("role")
    if role not in ("user", "assistant"):  # developer instructions are not conversation
        return None
    return _turn(role, _texts(payload.get("content"), ("input_text", "output_text")), CODEX_INJECTED)


# (parser, cheap substring that every kept line contains)
HOSTS = {"claude": (_claude, ('"user"', '"assistant"')), "codex": (_codex, ('"message"',))}


def _lines(path, max_bytes):
    if not isinstance(path, str) or not os.path.isabs(path):
        return
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError:
        return
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return
        size = info.st_size
        if size > max_bytes:
            stream.seek(size - max_bytes)
            stream.readline()  # the partial line
        for raw in stream:
            yield raw.decode("utf-8", "replace")


def read_turns(path, host, *, max_bytes=MAX_READ_BYTES):
    """Turns in order; () for an unsupported host or any unreadable transcript (the caller then routes on the prompt alone)."""
    if host not in HOSTS:
        return ()
    parse, needles = HOSTS[host]
    turns = []
    try:
        for line in _lines(path, max_bytes):
            if not any(n in line for n in needles):
                continue
            try:
                row = json.loads(line)
            except (ValueError, RecursionError):
                continue
            turn = parse(row) if isinstance(row, dict) else None
            if turn:
                turns.append(turn)
    except OSError:
        pass  # keep what was read
    return tuple(turns)

"""Strict Antigravity JSON result parser; automated run/resume remain unsupported."""

import json
from collections import namedtuple

from ..adapters.antigravity import AntigravityConfig
from . import session_env as session_env

Stream = namedtuple("Stream", "thread_id usage text")


class AntigravityResultError(ValueError):
    """Antigravity returned an error or an invalid result envelope."""


def session_argv(profile, prompt, sandbox, config=AntigravityConfig(), subagents=None):
    raise ValueError(
        "Antigravity mer run is unsupported because execution isolation is unverified; use mer route and a host-supported Subagent"
    )


def resume_argv(profile, thread_id, prompt, config=AntigravityConfig(), subagents=None):
    raise ValueError(
        "Antigravity mer run/resume is unsupported because execution isolation is unverified; use mer route and a host-supported Subagent"
    )


def parse_stream(text) -> Stream:
    """Parse one success envelope; retain raw usage without assuming billing or delta semantics."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise AntigravityResultError("Antigravity output is not one JSON object") from exc
    if not isinstance(data, dict) or data.get("status") != "SUCCESS":
        raise AntigravityResultError("Antigravity output is not a SUCCESS result")
    sid, response = data.get("conversation_id"), data.get("response")
    if not isinstance(sid, str) or not sid.strip() or not isinstance(response, str):
        raise AntigravityResultError("Antigravity result lacks conversation_id or response")
    usage = None
    if "usage" in data:
        usage = data["usage"]
        if not isinstance(usage, dict):
            raise AntigravityResultError("Antigravity usage is not an object")
        for key, count in usage.items():
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise AntigravityResultError(f"usage.{key} is not a nonnegative integer count")
        usage = dict(usage)
    return Stream(sid, usage, response)

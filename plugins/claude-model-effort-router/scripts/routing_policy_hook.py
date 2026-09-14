#!/usr/bin/env python3
"""Inject concise, non-blocking routing policy into Claude Code lifecycle events."""
from __future__ import annotations

import json
import sys


EVENTS = {"SessionStart"}
POLICY = (
    "For a new implementation, design, review, refactoring, or debugging task, "
    "invoke the model-effort:route skill before substantive repository work. Keep the complete "
    "route JSON and delegate each step with the Agent tool using its exact subagent_type and "
    "model; do not continue the task in the parent session. Reuse the existing route for "
    "same-scope follow-ups. Re-route for a distinct task, a new review, materially increased "
    "scope/risk, or a missing prior route. Do not route casual chat or status-only questions. "
    "If you are the classification-only process, classify only. If you are an executor given a "
    "complete route, execute only your assigned work; return escalation evidence instead of "
    "recursively routing. A route whose source is fallback is not successful semantic routing: "
    "report it and do not delegate it. Briefly show task_type, effective_level, "
    "selected model/effort, and source before delegation. Follow higher-priority instructions and "
    "explicit user constraints."
)


def hook_response(event: str, payload: object) -> dict[str, object]:
    if event not in EVENTS or not isinstance(payload, dict):
        return {}
    return {
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": POLICY,
        }
    }


def main(argv: list[str] | None = None) -> int:
    arguments = argv or sys.argv[1:]
    event = arguments[0] if len(arguments) == 1 else ""
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = None
    print(json.dumps(hook_response(event, payload)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

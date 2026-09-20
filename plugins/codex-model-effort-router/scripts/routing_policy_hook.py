#!/usr/bin/env python3
"""Inject concise, non-blocking routing policy into Codex lifecycle events."""
from __future__ import annotations

import json
import sys


EVENTS = {"SessionStart"}
POLICY = (
    "For implementation, design, review, refactoring, or debugging work, invoke "
    "model-effort:route first. Save the route JSON; replay without reclassifying. "
    "A route whose JSON pipeline block is non-null (code changes) runs via "
    "bin/codex-route --route-file (scripts/pipeline.py), which enforces plan, "
    "implement, test, review and fix: never the parent implementing directly, "
    "never those steps by hand with workers. Only pipeline-null routes "
    "(design/review) are delegated to a worker with its model/effort. Reuse the "
    "route for same-scope follow-ups. Re-route for a distinct task, a new review, materially "
    "increased scope/risk. Skip casual chat or status-only questions. As "
    "classification-only process, classify only. As executor given a complete "
    "route, run only assigned work; return escalation evidence, not recursive "
    "routing. Report fallback as fallback, not successful semantic routing. Show "
    "task_type, level, model/effort, source before delegating."
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

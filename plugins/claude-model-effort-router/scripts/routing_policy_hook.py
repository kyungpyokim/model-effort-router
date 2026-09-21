#!/usr/bin/env python3
"""Inject concise, non-blocking routing policy into Claude Code lifecycle events."""
from __future__ import annotations

import json
import sys


EVENTS = {"SessionStart"}
POLICY = (
    "For implementation, design, review, refactoring, or debugging work, invoke "
    "the model-effort:route skill first; do not continue in the parent session. "
    "A pipeline block is non-null (code changes): scripts/pipeline.py --route-file "
    "enforces plan, implement, test, review and fix; never the parent implementing "
    "directly. Only pipeline-null routes (design/review) are delegated with the Agent "
    "tool using exact subagent_type and model; inspect is read-only. Reuse same-scope "
    "follow-ups; re-route a new task, review, or materially increased scope/risk. "
    "Export MODEL_EFFORT_ROUTER_TEST_CMD before route generation and replay; trivial_edit "
    "uses its deterministic check. Preserve scope; reclassify INSPECT to MODIFY. Skip "
    "casual chat or status-only questions. executor given a complete route runs assigned "
    "work. A fallback-source route is not real routing: do not delegate it. Show "
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

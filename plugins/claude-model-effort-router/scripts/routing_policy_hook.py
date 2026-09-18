#!/usr/bin/env python3
"""Inject concise, non-blocking routing policy into Claude Code lifecycle events."""
from __future__ import annotations

import json
import sys


EVENTS = {"SessionStart"}
POLICY = (
    "For implementation, design, review, refactoring, or debugging work, invoke "
    "the model-effort:route skill first. Delegate steps with the Agent tool using "
    "exact subagent_type and model; do not continue in the parent session. Reuse "
    "the route for same-scope follow-ups. Re-route for a new task, review, or "
    "materially increased scope/risk. Skip casual chat or status-only questions. "
    "For bounded changes (L1-L3, no risk_flags, no security_review/migration_safety, "
    "single mode, no fable/astra), a single-agent fast path delegates once: focused "
    "tests, at most 1 review, no multi-agent chains, re-route only on new risk; "
    "never the parent implementing directly. As classification-only process, "
    "classify only. As executor given a complete route, run only assigned work; "
    "return escalation evidence, not recursive routing. A fallback-source route "
    "is not real routing: do not delegate it. Show task_type, level, model/effort, "
    "source before delegating. Follow higher-priority rules."
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

"""Audit trail background worker handler."""

import json

HANDLER = "audit"


def handle(job: dict) -> str:
    """Return the log record emitted after one job is handled."""
    return json.dumps(["audit", job["event"]])

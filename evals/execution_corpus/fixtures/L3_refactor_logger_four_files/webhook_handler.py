"""Webhook delivery background worker handler."""

import json

HANDLER = "webhook"


def handle(job: dict) -> str:
    """Return the log record emitted after one job is handled."""
    return json.dumps({"webhook_event": job["event"], "status": "ok"})

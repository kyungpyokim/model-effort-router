"""SMS delivery background worker handler."""

import json

HANDLER = "sms"


def handle(job: dict) -> str:
    """Return the log record emitted after one job is handled."""
    return json.dumps({"channel": "sms", "job": job["event"]})

"""Email delivery background worker handler."""

import json

HANDLER = "email"


def handle(job: dict) -> str:
    """Return the log record emitted after one job is handled."""
    return json.dumps({"message": f"email handled {job['event']}"})

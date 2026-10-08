"""JSONL event iteration shared by host execution and evaluation."""

import json


def iter_events(text):
    """Yield object events in order, skipping malformed JSON and other JSON values."""
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            yield event

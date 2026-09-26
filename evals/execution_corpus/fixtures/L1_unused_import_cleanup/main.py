"""One-line text summary utility."""

import json
import os
import textwrap


def summarize(raw: str) -> str:
    """Return a width-limited JSON summary of the raw text."""
    words = raw.split()
    payload = {"words": len(words), "first": words[0] if words else ""}
    return textwrap.shorten(json.dumps(payload), width=60)

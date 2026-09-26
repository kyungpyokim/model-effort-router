"""Label helpers."""

import re

LABEL_RE = re.compile(r"[^a-z0-9]+")


def slugify(label: str) -> str:
    """Lowercase a label and collapse invalid characters into dashes."""
    return LABEL_RE.sub("-", label.lower()).strip("-")

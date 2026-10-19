"""Prompt text sent to models lives in the .txt files next to this module; code only fills the ${placeholders}.

Edit a prompt by editing its file (.txt templates, or .json for the structured classifier questions). Write a literal `$` as `$$`. The final newline is the editor's, not the prompt's.
A `context_rule` value is inserted verbatim into the instructions that use it, so it takes a plain `$`, not `$$`.
"""

import json
from functools import lru_cache
from pathlib import Path
from string import Template

_DIR = Path(__file__).parent


@lru_cache(maxsize=None)
def raw(name):
    return (_DIR / f"{name}.txt").read_text(encoding="utf-8").removesuffix("\n")


def render(name, **values):
    """The prompt `name` with every ${placeholder} filled; a missing value raises KeyError."""
    return Template(raw(name)).substitute(values)


def data(name):
    """The parsed `name`.json, key order kept (it becomes the request body). A fresh copy: callers may modify it."""
    return json.loads(_DIR.joinpath(f"{name}.json").read_text(encoding="utf-8"))


def fill(value, **values):
    """`value` with ${placeholders} filled in every string at any depth; other values are kept, `value` is not modified."""
    if isinstance(value, str):
        return Template(value).substitute(values)
    if isinstance(value, list):
        return [fill(item, **values) for item in value]
    if isinstance(value, dict):
        return {key: fill(item, **values) for key, item in value.items()}
    return value

"""Antigravity PreInvocation: classify the latest user request from the transcript and advise Main per request.

The payload carries no prompt, only `transcriptPath`; the user turn is read from the transcript tail (regular file only,
bounded read). Advice only: Main's model and the Subagent controls are not changeable from a hook."""

import json
import os
import re

from ..context.transcripts import _lines
from ..difficulty.chain import ClassificationError
from ..policy.config import resolve_config
from ..policy.overrides import parse_override
from ..policy.router import route
from . import advice, hosts
from .codex_hooks import MAX_CHAIN_TIMEOUT_S, _registry, _with_timeout, load_configs
from .main_model import main_effort, main_model

TAIL_BYTES = 1024 * 1024
_REQUEST = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.DOTALL)
_CAVEAT = (
    " Antigravity's Subagent controls only select inherit, flash or pro tiers, so this model and effort are a "
    "preference; do not claim they were applied unless the host confirms it."
)


def latest_user_request(path):
    """Text inside the last explicit `<USER_REQUEST>` of the transcript; None when absent or the format differs."""
    found = None
    try:
        for line in _lines(path, TAIL_BYTES):
            if '"USER_INPUT"' not in line:
                continue
            try:
                row = json.loads(line)
            except (ValueError, RecursionError):
                continue
            if not isinstance(row, dict) or row.get("source") != "USER_EXPLICIT" or row.get("type") != "USER_INPUT":
                continue
            match = _REQUEST.search(row["content"]) if isinstance(row.get("content"), str) else None
            if match and match[1]:
                found = match[1]
    except OSError:
        pass
    return found


def _advice(data, env):
    """Advice text for this model invocation; "" when there is nothing to say; None when the request cannot be
    read from the transcript (the caller keeps its static advice)."""
    if data.get("invocationNum") != 0:
        return ""
    prompt = latest_user_request(data.get("transcriptPath"))
    if prompt is None:
        return None
    workspaces = data.get("workspacePaths") or []
    cwd = workspaces[0] if workspaces else os.getcwd()
    repo_cfg, user_cfg = load_configs(cwd, env)
    registry = _registry(env, "antigravity")
    cfg = resolve_config(task=parse_override(prompt)[0].as_config(), repo=repo_cfg, user=user_cfg, registry=registry)
    if cfg.mode != "auto":
        return ""
    limit = MAX_CHAIN_TIMEOUT_S // max(len(cfg.chain), 2)
    if cfg.timeout_s > limit:
        repo_cfg = _with_timeout(repo_cfg, limit)
    try:
        plan = route(
            prompt,
            repo_config=repo_cfg,
            user_config=user_cfg,
            registry=registry,
            host="antigravity",
            repo_summary=os.path.basename(os.path.normpath(cwd)),
        )
    except ClassificationError as exc:
        return advice.failure_line(exc.causes)
    main = main_model(data, "antigravity")
    effort = main_effort(data, "antigravity")
    text = advice.render(plan, "mer", hosts.ANTIGRAVITY, main, effort)
    if not text or text == advice.NO_ROUTE_MESSAGE:
        return text or ""
    return text + _CAVEAT


def routed_advice(data, env):
    """`_advice`, but a configuration or mapping error becomes a visible line instead of silently dropping the advice."""
    try:
        return _advice(data, env)
    except ValueError as exc:
        return f"[model-effort-router] routing error: {exc}; no routing advice this turn."

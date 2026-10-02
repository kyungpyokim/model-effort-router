"""Host selection for mer: `--host codex|claude`, else $MER_HOST, else codex. A host is its exec module + adapter."""
from collections import namedtuple

from ..adapters import claude as claude_adapter, codex as codex_adapter
from . import claude_exec, codex_exec

HOST_ENV = "MER_HOST"
Host = namedtuple("Host", "name exec resolve config switch_hint effort_word")
CODEX = Host("codex", codex_exec, codex_adapter.resolve, codex_adapter.CodexConfig(), "/model", "reasoning effort")
CLAUDE = Host("claude", claude_exec, claude_adapter.resolve, claude_adapter.ClaudeConfig(), "/model and /effort", "effort")
HOSTS = {h.name: h for h in (CODEX, CLAUDE)}


def get(name=None, env=None):
    """Explicit name, else env MER_HOST, else codex. Unknown names raise ValueError."""
    chosen = name or (env or {}).get(HOST_ENV) or "codex"
    if chosen not in HOSTS:
        raise ValueError(f"unknown host {chosen!r}; one of {sorted(HOSTS)}")
    return HOSTS[chosen]

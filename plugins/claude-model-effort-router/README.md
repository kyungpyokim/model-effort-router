# Claude Code Model Effort Router

Claude Code UserPromptSubmit integration for the shared MER runtime. The hook adds route and Subagent guidance; it does not change Main's model or launch a Subagent.

Install the shared runtime from the repository with `python3 scripts/install_core.py`. Use `MER_CORE_PATH="$PWD"` for development. See [the `mer` skill](skills/mer/SKILL.md) for role/effort behavior, Context Packet guidance, and `mer route` / single-worker `mer run` usage.

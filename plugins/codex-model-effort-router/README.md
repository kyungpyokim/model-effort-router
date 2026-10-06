# Codex Model Effort Router

Codex UserPromptSubmit integration for the shared MER runtime. The hook adds route and Subagent guidance; it does not mutate the current turn or spawn a Subagent.

Install the shared runtime from the repository with `python3 scripts/install_core.py`. Use `MER_CORE_PATH="$PWD"` for development. See the [`classify` skill](skills/classify/SKILL.md) for role/effort routing and the [`review` skill](skills/review/SKILL.md) for the implementation-to-review workflow.

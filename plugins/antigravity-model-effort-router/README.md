# Antigravity Model Effort Router

Antigravity hook integration for the shared MER runtime. The hook may classify and advise Main about role/effort, but Antigravity Subagent execution is unsupported because execution isolation has not been verified. Use the advice with Antigravity's supported workflow; do not use `mer run` on this host.

Install the shared runtime from the repository with `python3 scripts/install_core.py`. Use `MER_CORE_PATH="$PWD"` for development. See the [`classify` skill](skills/classify/SKILL.md) for role/effort routing and the [`review` skill](skills/review/SKILL.md) for review guidance when a supported write-capable worker is available.

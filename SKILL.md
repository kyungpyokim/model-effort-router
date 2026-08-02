---
name: model-effort-router
description: Build, install, validate, or update the bundled Model Effort Router plugins for Codex, Claude Code, and Antigravity. Use when a user wants coding tasks classified by difficulty and routed to a matching model plus reasoning-effort profile, or wants the cross-platform plugin package customized, tested, or repackaged.
---

# Model Effort Router Bundle

Use this skill to maintain the three platform-specific plugins under `plugins/`.

## Workflow

1. Read `references/routing-policy.md` before changing difficulty levels or hard-floor rules.
2. Keep the shared mapping in `config/model-map.json` as the source of truth.
3. Apply mapping changes consistently to Codex TOML agents, Claude Code Markdown agents, and Antigravity launcher patterns.
4. Run `python3 scripts/validate_bundle.py` and `python3 -m unittest discover -s tests -v` after every change.
5. Validate the Claude plugin with `claude plugin validate` when Claude Code is installed.
6. Validate the Antigravity plugin with `agy plugin validate` when Antigravity CLI is installed.
7. Package the complete bundle, not only modified files.

## Constraints

- Route by difficulty, not by programming language or feature category.
- Treat model and effort as one profile.
- Preserve the five levels and six-factor scoring unless the user explicitly requests a different policy.
- Keep account-dependent model names editable in configuration.
- Do not claim that a running session can always change models internally. Use the platform agent definitions where supported and the launcher scripts when a new process is required.

---
name: model-effort
description: Build, install, validate, or update the bundled Model Effort Router plugins for Codex, Claude Code, and Antigravity. Use when a user wants coding tasks classified by difficulty and routed to a matching model plus reasoning-effort profile, or wants the cross-platform plugin package customized, tested, or repackaged.
---

# Model Effort Router Bundle

Use this skill to maintain the three platform-specific plugins under `plugins/`.

## Workflow

1. Read `references/routing-policy.md` before changing task types, difficulty levels, risk-flag rules, or the Codex matrix.
2. Keep the shared mapping in `config/model-map.json` as the source of truth.
3. Edit only the bundle-root copies of `scripts/router.py`, `config/model-map.json`, and `references/routing-policy.md`, then run `python3 scripts/sync_bundle.py` to propagate them into every plugin copy.
4. Run `python3 scripts/validate_bundle.py` and `python3 -m unittest discover -s tests -v` after every change.
5. Validate the Claude plugin with `claude plugin validate` when Claude Code is installed.
6. Validate the Antigravity plugin with `agy plugin validate` when Antigravity CLI is installed.
7. Package the complete bundle, not only modified files.

## Constraints

- Route Codex tasks through the `task_type × level` matrix; route Claude Code and Antigravity by level.
- Treat model and effort as one profile.
- Preserve the five task types, five levels, six-factor scoring, and code-side security L4 floor unless the user explicitly requests a different policy.
- Keep account-dependent model names editable in configuration.
- Do not claim that a running session can always change models internally. Use the platform agent definitions where supported and the launcher scripts when a new process is required.

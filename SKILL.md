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

- Route every platform through its `task_type × level` matrix; each platform maps the shared luna/sol roles onto its own models.
- Treat model and effort as one profile.
- Preserve the five task types, five levels (L1~L5) plus the `elevated` and `critical` risk tiers, fact-based classifier with `DIFFICULTY_RULES` in `scripts/router.py`, cascading classifier, and code-side security floors (elevated tier for security/payment changes, L5 for a critical security domain, L4 for security reviews, elevated tier for a critical-domain trust-boundary change; irreversible/ledger/crypto = yes is the critical tier) unless the user explicitly requests a different policy.
- Keep the code-change workflow: every code-change route requires a caller-supplied deterministic test command and fails closed without one. Only a gated `trivial_edit` skips plan and review, never its required test; every other `implementation` / `local_refactoring` / `architectural_refactoring` route runs the L2-or-higher judge rows (`max(level, WORKFLOW_MIN_LEVEL)`) for plan, launcher-run tests, and merged review. The planner is skipped only when it equals the implementer.
- Keep account-dependent model names editable in configuration.
- Do not claim that a running session can always change models internally. Use the platform agent definitions where supported and the launcher scripts when a new process is required.

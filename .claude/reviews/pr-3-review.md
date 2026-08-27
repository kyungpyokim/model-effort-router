# PR Review: #3 — feat(router): Paperthin 핵심 패턴 통합 (readchk, autobahn, re0/debloat)

**Reviewed**: 2026-08-27
**Re-reviewed**: 2026-08-27 (HEAD `4577b45`)
**Author**: kyungpyokim
**Branch**: codex/paperthin-integration-v1 → main
**Decision**: APPROVE (all MEDIUM findings resolved in `4577b45`)

## Re-Review (HEAD `4577b45`)

New commit since the first review: `4577b45` "fix(router): PR #3 리뷰 피드백 반영". It
directly addresses the prior findings.

| Prior finding | Status | Evidence |
|---|---|---|
| MEDIUM 1 — guard skips claude-code/antigravity single-stage | **RESOLVED** | `_single_stage_command` now computes `has_security_flag` and prepends `[{AUTOBAHN_SCOPE_GUARD}]` to the prompt for the `shell_command()` path. Verified: claude-code, antigravity, codex all inject the guard on a `security_sensitive` flag and stay clean without one. |
| MEDIUM 2 — duplicated instruction literal | **RESOLVED** | `AUTOBAHN_SCOPE_GUARD_INSTRUCTION` is now the single source; `AUTOBAHN_SCOPE_GUARD` is an f-string over it, and `result_payload()` references the constant instead of an inline copy. New test `test_autobahn_scope_guard_dry_constant` pins the relationship. |
| MEDIUM 3 — tests only cover codex | **RESOLVED** | `test_autobahn_scope_guard_in_claude_and_antigravity_single_stage` subtests both platforms (present + absent cases). |
| LOW 4 — planner instructions lack the guard | **RESOLVED** | `stage_commands` two-stage path now appends `AUTOBAHN_SCOPE_GUARD` to `PLANNER_INSTRUCTIONS_TEMPLATE` too; test updated to assert guard in `planner`. |
| LOW 5 — readchk `ambiguity=2` can nudge levels | **RESOLVED (documented)** | `routing-policy.md` (all 4 copies) now notes the one-level escalation effect. |
| LOW 6 — 4× file duplication | **NOT AN ISSUE (structural constraint)** | Each plugin is distributed/installed self-contained, so per-plugin copies of `router.py` / `routing-policy.md` are inherent to the packaging model. Already handled correctly: one logical source + `sync_bundle.py` propagation + `validate_bundle.py --check` enforcing byte-identity in CI. No action needed, now or in future PRs. |

Minor note (non-blocking): guard delivery differs by platform — codex appends to a
separate instructions param, claude-code/antigravity wrap it as `[...]` inside the `-p`
prompt. Both are valid given the respective CLIs; no action needed.

### Re-Review Validation

| Check | Result |
|---|---|
| Tests | Pass — `python3 -m unittest discover -s tests` → **43/43 OK** (was 41; +2 new) |
| Bundle validation | Pass — `scripts/validate_bundle.py` → "bundle validation passed" |
| Bundle sync | Pass — `scripts/sync_bundle.py --check` → "bundle copies are in sync" |
| 4-copy identity | Pass — `scripts/router.py` byte-identical to all 3 plugin copies |
| Guard injection smoke | Pass — codex / claude-code / antigravity single-stage all inject the guard on a security flag, none inject it without |

No new issues found. Decision upgraded from APPROVE-with-comments to **APPROVE**.

---

## Original Review (HEAD `8c988f2`)

## Summary

Surgical, low-risk prompt/policy changes: injects `readchk` (intent restatement + referent
resolution) into the classifier prompt, `re0`/`debloat` hygiene into the two-stage planner and
implementer templates, and an `AUTOBAHN_SCOPE_GUARD` directive plus a `scope_guard` JSON payload
field when a security-floor flag is active. All 41 tests pass, bundle validation and the 4-copy
sync check pass. No CRITICAL/HIGH issues. Main gap: the Autobahn guard is only wired into the
Codex single-stage path, not claude-code/antigravity single-stage, which contradicts the PR
description.

## Findings

### CRITICAL
None

### HIGH
None

### MEDIUM

1. **Autobahn scope guard skips claude-code / antigravity single-stage runs**
   `scripts/router.py:543-547` (`_single_stage_command`). The guard is appended only in the
   `result.platform == "codex"` branch; the `shell_command()` fallback for claude-code and
   antigravity receives no scope-carve text. Two-stage runs are covered for all three platforms
   (via `execute_instructions`), and `result_payload()` emits `scope_guard` for every platform,
   but `--format command` / direct shell execution on claude-code/antigravity carries nothing.
   The PR description claims injection into "단일 및 2단계 에이전트 지침" — that is only true for
   Codex single-stage. The `level-4-advanced` claude/antigravity agent files carry only generic
   "security" wording, not the carve directive.
   Verified: `router.py --platform claude-code --format command --task-type implementation
   --level L1 "fix OAuth bug"` →
   `claude --agent level-4-advanced --model sonnet --effort xhigh -p 'fix OAuth bug'` (no guard).
   → Fix: wire the guard into `shell_command()` / the single-stage claude+agy path, or narrow
   the docs and PR claim to "Codex single-stage + all two-stage".

2. **Duplicated instruction literal (DRY)**
   `AUTOBAHN_SCOPE_GUARD` constant and the inline `"instruction"` string in `result_payload()`
   are the same sentence minus the `"Autobahn scope guard: "` prefix. With 4 synced copies of
   `router.py`, that is 8 places one wording change must land. Derive the payload string from the
   constant (strip the prefix) or reference a single shared source.

3. **New tests only exercise the Codex platform**
   `PaperthinIntegrationTests` asserts guard injection/omission for `routed()` (defaults to
   `platform="codex"`) only. The gap in finding #1 is invisible to CI. Add a case pinning the
   intended claude-code/antigravity single-stage behavior (guard present, or explicitly absent).

### LOW

4. **Two-stage planner instructions do not get the scope guard** — only `execute_instructions`
   does (`stage_commands`, `router.py:556-558`). Since the plan is what defines how sensitive
   scope is carved, a scope-aware planner may be preferable; otherwise note the deliberate choice.

5. **`readchk` forcing `ambiguity=2` on genuine forks** can nudge borderline tasks up one level
   through the factor score. Likely the intended bias-to-escalate behavior, but worth a one-line
   note in `routing-policy.md`.

6. **4× file duplication** (`scripts/`, `plugins/{codex,claude,antigravity}-*/scripts/`,
   plus 4× `routing-policy.md`) is the repo's pre-existing `sync_bundle.py` pattern, not
   introduced here. Sync check currently passes; every future prompt tweak must keep all copies
   identical.

## Validation Results

| Check | Result |
|---|---|
| Type check | Skipped (no pyproject/mypy config; pure stdlib) |
| Lint | Skipped (no ruff/flake8 config in repo) |
| Tests | Pass — `python3 -m unittest discover -s tests` → 41/41 OK |
| Bundle validation | Pass — `scripts/validate_bundle.py` → "bundle validation passed" |
| Bundle sync | Pass — `scripts/sync_bundle.py --check` → "bundle copies are in sync" |
| CLI smoke | Pass — codex single-stage security task injects `Autobahn scope guard`; JSON payload carries `scope_guard.policy = "autobahn_scope_carve"` |

## Files Reviewed

- `.gitignore` — Modified (adds `.worktrees/`)
- `scripts/router.py` — Modified (readchk/re0/debloat prompt text; `AUTOBAHN_SCOPE_GUARD`; scope-guard injection in `_single_stage_command`, `stage_commands`, `result_payload`)
- `references/routing-policy.md` — Modified (policy documentation)
- `plugins/codex-model-effort-router/scripts/router.py` — Modified (synced copy)
- `plugins/codex-model-effort-router/references/routing-policy.md` — Modified (synced copy)
- `plugins/claude-model-effort-router/scripts/router.py` — Modified (synced copy)
- `plugins/claude-model-effort-router/references/routing-policy.md` — Modified (synced copy)
- `plugins/antigravity-model-effort-router/scripts/router.py` — Modified (synced copy)
- `plugins/antigravity-model-effort-router/references/routing-policy.md` — Modified (synced copy)
- `tests/test_router.py` — Modified (adds `PaperthinIntegrationTests`, 4 tests)

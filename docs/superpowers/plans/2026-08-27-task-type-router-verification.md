# Task-Type Router Verification and Release Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the supplied task-type router design is complete and releasable; repair only a demonstrated gap.

**Architecture:** `scripts/router.py` owns policy and command generation. `config/model-map.json` is the editable matrix, and `scripts/sync_bundle.py` propagates shared root artifacts to the three plugin bundles. Codex L3+ architectural refactoring runs a planner-to-executor plan-file chain.

**Tech Stack:** Python standard library, Bash launchers, JSON, TOML.

**Spec:** `/Users/kimkyungpyo/.codex/attachments/8733c3e3-52bd-45fc-9a18-de774d723a71/pasted-text.txt`

## Global Constraints

- Keep the five task types, L1-L5, six risk flags, and the code-side L4 security floor.
- Keep `implementation / L3 / luna xhigh` as the automatic-classifier fallback; explicit invalid config must fail.
- Edit only root shared sources, then run `python3 scripts/sync_bundle.py`; never patch plugin copies separately.
- Do not add dependencies, persistence, or another abstraction. The existing temporary plan-file protocol is sufficient.
- Keep routing authority in this router. Paperthin principles may improve classification and completion checks, but Paperthin skills must not become a second model-selection authority.

---

## Current-State Finding

The design is already implemented in the checked-in source bundle. `scripts/router.py` has the typed classifier schema, override, risk escalation, matrix lookup, JSON payload, two-stage command chain, and route-file replay. The root matrix, policy documentation, plugin copies, and regression tests also contain the specified behavior. Task 1 is therefore the completion gate; a green result ends work without a duplicate source change. This plan document itself may be an untracked worktree artifact and does not indicate a router-source change.

## Deferred Paperthin Follow-up (Out of Scope)

No Paperthin component is implemented or released by this plan. The router remains the only model/effort selection authority; this plan only verifies the checked-in router contract.

| Future idea | Entry condition and boundary |
|---|---|
| `modelchk` / `readchk` | Consider only after a measured classifier error. Keep one classifier call; do not add a second preflight model call. The new plan must define the evaluation corpus and its failure threshold. |
| `sip` QA gate | Consider only after a demonstrated verification gap. A separate plan must define the owner, selected-check input/output schema, command execution point, failure exit code, artifact retention, and skipped-check reporting. |
| `prism` | Consider only after an L4-L5 planning defect. A separate plan must define its trigger, stage output, timeout, and failure behavior. |
| `ssotize` | Retain the existing rule: root router, model map, and policy are canonical; `sync_bundle.py` copies only those three shared artifacts. |
| `hate`, `re0-loop`, `nba`, `catchup` | Remain outside automatic router execution. |

For a future accepted change, first add a failing test for the measured need, then change the root source and use the existing bundle synchronization flow.

### Task 1: Run the implementation-completeness gate

**Files:** Inspect `scripts/router.py:22-126,437-577,608-763`, `config/model-map.json`, `tests/test_router.py:1-528`, and `references/routing-policy.md:1-156`. Test `tests/test_router.py`.

**Interfaces:** Consumes the supplied spec and checked-in root bundle. Produces a green evidence record, or one concrete failed contract for Task 2.

- [ ] **Step 1: Validate package structure and copy synchronization.** Run `python3 scripts/validate_bundle.py`, `python3 scripts/sync_bundle.py`, then `git diff --exit-code -- scripts/router.py config/model-map.json references/routing-policy.md plugins`. Expect `bundle validation passed`, `bundle copies are in sync`, and no source diff.
- [ ] **Step 2: Run all router regression tests.** Run `python3 -m unittest discover -s tests -v`. Expect every matrix cell, the hard security floor, two-stage chain, replay, cleanup, and root-to-plugin hash checks to pass.
- [ ] **Step 3: Optionally collect a live-classifier smoke record.** Run `python3 scripts/router.py --platform codex --task-type architectural_refactoring --level L3 --format json "restructure module boundaries"` only where a live Codex classifier is available. Record the returned JSON for diagnosis, but do not use its level, risk flags, or stage shape as a pass/fail gate: explicit L3 is a minimum and does not bypass classification. Step 2 is the deterministic contract gate.
- [ ] **Step 4: Stop on green.** If all checks pass, do not create a code commit. If a check fails, retain its exact command output and proceed only with Task 2.

### Task 2: Repair the demonstrated root contract

**Files:** Modify only the failed root source: `scripts/router.py` for validation/escalation/staging/payload issues or `config/model-map.json` for mapping issues. Test `tests/test_router.py`.

**Interfaces:** Consumes one failed assertion or mismatch from Task 1. Produces a compatible `RouteResult`, JSON payload, and command chain.

- [ ] **Step 1: Add a focused failing test at the current boundary.** Use `EscalationTests` for risk policy, `MatrixTests` for a task-type/level cell, or `CommandAndLauncherTests` for command or JSON structure. Assert exact values, e.g. L3 architectural refactoring stages must be `planner/gpt-5.6-sol/high` then `implementer/gpt-5.6-luna/xhigh`.
- [ ] **Step 2: Confirm the pre-change failure.** Run the exact test method, such as `python3 -m unittest tests.test_router.MatrixTests.test_every_matrix_cell_matches_the_final_spec -v`. The failure must name the incorrect level, profile, command dependency, or payload field.
- [ ] **Step 3: Make the smallest root fix.** Change only the matrix cell or shared function that caused the failure. Preserve the L4 security floor, fallback, and `schema_version: 1` contracts.
- [ ] **Step 4: Verify and commit the correction.** Run `python3 -m unittest tests.test_router -v` and `python3 scripts/validate_bundle.py`. Stage only actual changed root and test files, then commit `fix(router): preserve task-type routing contract`.

### Task 3: Synchronize changed shared artifacts

**Files:** Generated changes only in `plugins/*/scripts/router.py`, `plugins/*/config/model-map.json`, and `plugins/*/references/routing-policy.md`. Test `tests/test_router.py`.

**Interfaces:** Consumes a root shared-file correction. Produces byte-identical deployment copies across every plugin.

- [ ] **Step 1: Generate copies from roots.** Run `python3 scripts/sync_bundle.py`. Expect only corresponding plugin copies to change.
- [ ] **Step 2: Verify hashes and package contents.** Run `python3 -m unittest tests.test_router.BundleSyncTests.test_plugin_copies_match_the_bundle_root -v` and `python3 scripts/validate_bundle.py`. Expect all checks to pass.
- [ ] **Step 3: Commit generated copies with their root change.** Stage `plugins` with the changed root/test paths. Amend Task 2 only if it is still local; otherwise commit `chore(bundle): sync router copies`.

### Task 4: Align public documentation only for a changed contract

**Files:** `references/routing-policy.md`, `README.md`, `plugins/codex-model-effort-router/README.md`, `plugins/codex-model-effort-router/skills/route/SKILL.md`, `plugins/claude-model-effort-router/README.md`, and `plugins/antigravity-model-effort-router/README.md`.

**Interfaces:** Consumes an actual user-visible policy or CLI change from Task 2. Produces source-of-truth policy and launcher guidance matching runtime behavior.

- [ ] **Step 1: Update the root policy first.** Document the exact changed enum, matrix profile, risk rule, CLI flag, JSON field, or plan-file lifecycle. Keep design-only architecture requests as `design` and runtime router selection above TOML fallback.
- [ ] **Step 2: Update every affected public entry point.** Copy only the changed contract into the root README and each affected plugin README. Update the Codex route skill when Codex skill behavior changes. Keep examples executable. Document that route-file replay is supported by the root CLI, `codex-route`, and `claude-route`; `agy-route` remains task-only unless Task 2 changes that launcher and adds a regression test.
- [ ] **Step 3: Sync and validate the two documentation classes.** Run `python3 scripts/sync_bundle.py` and `python3 -m unittest tests.test_router.BundleSyncTests.test_plugin_copies_match_the_bundle_root -v` for the three synchronized artifacts, then run `git diff --check` and inspect every changed README/skill diff. `sync_bundle.py` does not synchronize README or skill files.

## Final Validation

Run `python3 scripts/validate_bundle.py`, `python3 -m unittest discover -s tests -v`, `git diff --check`, and `git status --short`.

## Acceptance

- [ ] The supplied design is proven complete without duplicate implementation, or every demonstrated gap is fixed at its root source.
- [ ] All task-type/level cells, security floors, fallback behavior, and two-stage plan dependency are covered by passing tests.
- [ ] All plugin copies match root shared artifacts.
- [ ] Every affected launcher document states the same public contract; route-file replay support is not claimed for `agy-route` unless that launcher is changed and tested.

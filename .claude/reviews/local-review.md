# Code Review: model-effort-router (local, full-project)

**Reviewed**: 2026-08-03
**Scope**: Entire project — the directory is not a git repository, so there was no diff to scope to.
**Decision at review time**: REQUEST CHANGES (0 CRITICAL, 3 HIGH, 7 MEDIUM, 6 LOW)
**Status after this session**: all 3 HIGH issues fixed and verified; MEDIUM/LOW remain open.

## Summary

A well-structured difficulty-based routing bundle with a sound core policy: hard floors are
independent of scoring and never lower a level, generated shell commands are correctly quoted,
and no credentials or debug residue are present. Three HIGH defects made the shipped artifacts
misbehave in practice — a launcher that breaks on install, a scoring flag that silently discards
signal, and an unbounded subprocess call that hangs. All three are now fixed with regression tests.

## Findings

### CRITICAL

None.

### HIGH — all fixed in this session

**H1. Installed `agy-route` launcher could never run** — `scripts/install_plugins.py:40`

`shutil.copy2` placed the launcher in `~/.local/bin`, but the script derives the bundle root from
its own location (`ROOT_DIR="$SCRIPT_DIR/.."`). The copy therefore looked for
`~/.local/scripts/router.py`, which does not exist.

Reproduction before the fix:

```
can't open file '.../fakehome/scripts/router.py': [Errno 2] No such file or directory
```

Fix: the three launchers now resolve their own real path through symlinks, honour a
`MODEL_EFFORT_ROUTER_ROOT` override, and fail with an actionable message if the bundle is missing.
`install_antigravity()` creates a symlink instead of a copy and reports what it replaces.

**H2. A single `--<factor>` flag silently zeroed the other five** — `scripts/router.py:242`

Supplying any explicit factor discarded all keyword scoring and defaulted the rest to 0.

| Invocation | Before | After |
|---|---|---|
| no factor flags | `score=8` → L4 | `score=8` → L4 |
| `--scope 2` on the same task | `score=2` (scope=2, rest 0) | `score=8` (scope=2, keyword signal retained) |

The task above happened to carry a hard-floor keyword, which masked the drop; without one the
level would have fallen from L4 to L1. Fix: explicit factors now merge over keyword-derived
scores instead of replacing them, and the rationale records which factors were overridden.

**H3. `agy models` was called with no timeout** — `scripts/router.py:132`

`agy-route --detect-antigravity-models` could hang indefinitely; during this review the call was
still running after 120s with zero output and had to be killed. A non-zero exit also raised an
uncaught `RuntimeError` traceback rather than falling back.

Fix: `read_available_models()` takes a `timeout` (default 20s, tunable via `--detect-timeout`),
converts `TimeoutExpired`/`OSError` into `RuntimeError`, and `main()` degrades to the configured
fallback model with a stderr notice.

Verified:

```
model detection failed (`agy models` timed out after 2s); using configured fallbacks
L5 (critical) | score=0 | model=Claude Opus 4.6 (Thinking) | effort=embedded in model
exit=0
```

### MEDIUM — open

**M1. `config.levels[*].score_min/score_max` are decorative** — `scripts/router.py:102-111`
Thresholds are hardcoded in `level_for_score()`. Editing L1's range to 0-11 leaves a score of 7
mapping to L3. This contradicts `SKILL.md:13` ("config as the source of truth"). Derive the
thresholds from config, or drop the fields.

**M2. Antigravity regexes are over-broad and tier-overlapping** — `config/model-map.json:77-117`
Bare patterns `"Low"`, `"Medium"`, `"Thinking"` are `re.search` with `IGNORECASE`, so they match
inside unrelated names (`Slow`, `Follow`). L3 also lists `Sonnet.*Thinking`, an L4-tier model, so
L3 can select a stronger model than L4. Add word boundaries and remove the cross-tier entries.

**M3. Keyword matching is naive substring containment** — `scripts/router.py:48-49`
`"api" in "rapid"`, `"test" in "latest"/"contest"`, `"error" in "terror"` all match. A pure typo
fix scores 2: `"rapid typo fix in the latest contest banner"` → `scope=1, verification=1`.
Use word-boundary matching for short English tokens; the Korean keywords are fine as-is.

**M4. `validate_bundle.py` is a no-op under `-O`** — `scripts/validate_bundle.py:29-43`
Every check is a bare `assert`, so `python3 -O scripts/validate_bundle.py` prints
"bundle validation passed" without validating anything. Use explicit raises like `require()`.

**M5. Four verbatim copies with no sync check in the validator**
`router.py`, `model-map.json` and `routing-policy.md` exist at the root and in all three plugins.
`validate_bundle.py` never compares them. A `BundleParityTests` case now guards this from the test
side, but the validator should check it too, or the copies should be generated at package time.

**M6. Launchers re-parse an already-safe command string** — `bin/*-route`
`exec bash -c "${COMMAND}"` is **not** currently exploitable: `shlex.join` quoting was verified
against hostile input (`fix bug'; touch /tmp/PWNED; echo '` round-trips safely). It remains a
structure where one missed quote becomes RCE. Emitting NUL-separated argv and exec'ing an array
would remove the class entirely.

**M7. Test coverage gaps beyond the new regression tests**
Still untested: `shell_command()` output shape per platform, `main()` argument parsing,
`read_available_models()` stdout parsing, and hard-floor interaction with `--level`.

### LOW — open

- `clamp_score()` raises rather than clamping — the name contradicts the behaviour (`router.py:37`).
- `lstrip("-*• ")` strips any leading combination of those characters, and the
  `startswith(("available","models"))` filter can drop a legitimate model name (`router.py:137-138`).
- Unknown platform or level raises a bare `KeyError` from `route()` (`router.py:177`); argparse
  shields the CLI but not library callers.
- A malformed regex in config surfaces as an uncaught `re.error` (`router.py:146`).
- `shutil.which(x) or x` followed by `check=True` yields a raw `FileNotFoundError` traceback when a
  platform CLI is absent (`install_plugins.py:19,26,33`).
- Model ids (`gpt-5.6-*`, `Gemini 3.5 Flash`, `Claude Opus 4.6 (Thinking)`) are account- and
  release-dependent and could not be verified here. Keeping them in config is the right design;
  the README should tell users to confirm against `codex --help` / `agy models` first.

## Verified as correct

- Every CLI flag the router emits exists: `claude --model` / `--effort` (accepts exactly
  `low, medium, high, xhigh, max`, matching the config), `codex exec -m -c`, and
  `agy --model` / `--prompt` / `--prompt-interactive` / `agy models`.
- Command generation is injection-safe under adversarial task text.
- No hardcoded credentials or tokens; MIT license present in the root and each plugin.
- Recursion guard ("do not invoke the router recursively") is stated consistently in all ten agent
  definitions and both plugin skills.

## Validation Results

| Check | Result |
|---|---|
| Type check | Skipped — no mypy/pyright configuration in the project |
| Lint | Skipped — no ruff/flake8 configuration in the project |
| Tests | Pass — 20/20 (`python3 -m unittest discover -s tests`), up from 6 |
| Build | N/A — no build step |
| `scripts/validate_bundle.py` | Pass (see M4 for the caveat) |
| `python3 -m py_compile` on all Python files | Pass |
| `bash -n` on all three launchers | Pass |

## Files Changed in This Session

| File | Change |
|---|---|
| `scripts/router.py` | Modified — H2 factor merge, H3 timeout and graceful fallback, `--detect-timeout` |
| `plugins/*/scripts/router.py` (3) | Modified — re-mirrored from the root copy |
| `plugins/antigravity-model-effort-router/bin/agy-route` | Modified — H1 symlink resolution, `MODEL_EFFORT_ROUTER_ROOT`, `MODEL_EFFORT_ROUTER_MODELS_FILE`, `MODEL_EFFORT_ROUTER_PRINT_ONLY` |
| `plugins/claude-model-effort-router/bin/claude-route` | Modified — H1 symlink resolution, print-only mode |
| `plugins/codex-model-effort-router/bin/codex-route` | Modified — H1 symlink resolution, print-only mode |
| `scripts/install_plugins.py` | Modified — symlink instead of copy, reports replaced launcher |
| `tests/test_router.py` | Modified — added `ExplicitFactorTests`, `ModelDetectionTests`, `LauncherTests`, `BundleParityTests` |

## Recommended Next Steps

1. M1 and M4 are small and remove two false-confidence signals — do these next.
2. M3 (word-boundary keyword matching) has the largest effect on real routing accuracy.
3. M2 needs a decision on Antigravity tier ordering before the regexes are rewritten.

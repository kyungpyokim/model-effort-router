# helpers

Tiny numeric helper module.

Run the acceptance checks from the fixture root:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
```

## Fixture metadata

- Case: L1_rename_local_variable (local_refactoring, L1)
- Task: Rename local variable foo to bar in helper function
- Expected initial test outcome: FAIL (pytest exit status 1)
- The behavior checks stay green while the local-rename check fails on the
  initial state and passes once `helper()` uses `bar` instead of `foo` with
  identical behavior.

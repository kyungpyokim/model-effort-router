# listview

Pagination math for a list view.

Run the acceptance checks from the fixture root:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
```

## Fixture metadata

- Case: L2_simple_bug_fix (implementation, L2)
- Task: Fix off-by-one error in pagination calculation in view.py
- Expected initial test outcome: FAIL (pytest exit status 1)
- The boundary checks reproduce the off-by-one against the initial state
  (`total_pages` drops the final partial page) and pass once the boundary
  calculation in `view.py` is fixed.

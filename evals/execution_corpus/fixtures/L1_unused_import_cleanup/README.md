# wordcount

Tiny one-line text summarizer.

Run the acceptance checks from the fixture root:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
```

## Fixture metadata

- Case: L1_unused_import_cleanup (local_refactoring, L1)
- Task: Remove unused imports in main.py
- Expected initial test outcome: FAIL (pytest exit status 1)
- The AST import check fails while `main.py` keeps an unused import and passes
  once it is removed; the behavior checks must stay green unchanged.

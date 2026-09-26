# triplesplit

Key/value string parsing shared by three related test modules.

Run the acceptance checks from the fixture root:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
```

## Fixture metadata

- Case: L3_local_refactor_three_files (local_refactoring, L3)
- Task: Refactor string parsing utils across 3 related test files
- Expected initial test outcome: FAIL (pytest exit status 1)
- The string-parsing behavior checks stay green on the initial state while the
  shared-parser check fails; it passes only after the parsing utils are
  refactored across the three related files so exactly one shared parser owns
  the quote-stripping logic.

## Expected shape after the refactor

The three related files (`tests/check_query_parsing.py`,
`tests/check_header_parsing.py`, `tests/check_cookie_parsing.py`) keep parsing
their own formats and keep their behavior checks green, but the duplicated
`_split_pair` helper moves into a single shared parser module that all three
import from. Behavior of the helper is unchanged: split on the separator,
strip whitespace from both sides, strip surrounding double quotes from the
value.

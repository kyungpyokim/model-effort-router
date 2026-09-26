# datekit

Tiny date/label helpers for `utils.py`.

Run the acceptance checks from the fixture root:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
```

## Fixture metadata

- Case: L2_single_file_helper (implementation, L2)
- Task: Add helper function to parse date string in utils.py
- Expected initial test outcome: FAIL (pytest exit status 1)
- The date-parse checks fail until `utils.py` provides the helper and pass
  without any other change.

## Required helper contract

```python
def parse_date(value: str) -> datetime.date
```

- Accepts ISO `YYYY-MM-DD` strings (for example `"2026-09-26"`) and returns
  the corresponding `datetime.date`.
- Raises `ValueError` for anything else: malformed strings, non-padded or
  slash-separated forms, and impossible dates such as `"2026-02-30"`.

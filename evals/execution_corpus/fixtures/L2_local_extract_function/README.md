# payloadguard

Payload validation for users and orders.

Run the acceptance checks from the fixture root:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
```

## Fixture metadata

- Case: L2_local_extract_function (local_refactoring, L2)
- Task: Extract duplicate validation logic into a local function in validator.py
- Expected initial test outcome: FAIL (pytest exit status 1)
- The behavior checks stay green on the initial state while the duplication
  check fails; it passes only after the duplicated code validation logic in
  `validator.py` is extracted into one shared local function.

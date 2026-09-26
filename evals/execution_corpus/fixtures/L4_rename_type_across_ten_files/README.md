# profile-services

Ten profile services sharing one user-profile type.

Run the acceptance checks from the fixture root:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
```

## Fixture metadata

- Case: L4_rename_type_across_ten_files (local_refactoring, L4)
- Task: Rename UserProfileDTO across 10 service files
- Expected initial test outcome: FAIL (pytest exit status 1)
- The consistency checks fail while any file still references the old type
  name `UserProfileDTO`; the behavior checks stay green throughout. After the
  rename, `models.py` defines `UserProfile`, every service builds profiles
  through it, and no file mentions the old name anymore.

## Contracts

- The rename target is `UserProfile` (defined in `models.py`); the old name
  `UserProfileDTO` must appear in no fixture source file afterwards.
- All ten services (`service_01.py` ... `service_10.py`) must construct
  profiles through `models.UserProfile` — deleting the type usage instead of
  renaming it does not satisfy the task.
- Behavior is unchanged: `build_profile(record)` copies the record and
  returns `{"id", "name", "source"}` with `source` set to the service's own
  name (`"service_01"` ... `"service_10"`); the input record is never
  mutated.

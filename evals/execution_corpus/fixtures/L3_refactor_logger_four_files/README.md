# workerlog

Background worker handlers that must share one structured log format.

Run the acceptance checks from the fixture root:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
```

## Fixture metadata

- Case: L3_refactor_logger_four_files (local_refactoring, L3)
- Task: Standardize structured logging format across 4 background worker handler files
- Expected initial test outcome: FAIL (pytest exit status 1)
- The worker handler checks fail against the initial inconsistent per-handler
  log formats and pass only after all four background worker handlers emit the
  standardized structured logging format.

## Standard record

Every `handle(job: dict) -> str` in the four handler files must return the same
structured format: a JSON object with exactly the keys `event` (from
`job["event"]`), `handler` (the module's `HANDLER` constant) and `level`
(`job.get("level", "info")`), serialized with `json.dumps(..., sort_keys=True)`
so the key order is deterministic.

Example: `email_handler.handle({"event": "job.finished"})` returns
`{"event": "job.finished", "handler": "email", "level": "info"}`.

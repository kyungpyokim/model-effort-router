# profileapi

User-profile REST API served by a single in-process module (no server, no
network — responses are plain `Response` objects).

Run the acceptance checks from the fixture root:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
```

## Fixture metadata

- Case: L4_public_api_change (implementation, L4)
- Task: Change REST API response envelope from data/error to standard RFC7807 problem details
- Expected initial test outcome: FAIL (pytest exit status 1)
- The API contract checks fail against the initial state, which still wraps
  everything in the legacy `data`/`error` envelope with `application/json`;
  they pass only after every response uses the RFC7807 problem-details
  envelope for errors and returns bare resources on success.

## Contracts

- Success responses (status 200) carry `content_type` `application/json` and
  their body is the bare resource object — no `data` or `error` wrapper keys.
- Error responses (403, 404) carry `content_type`
  `application/problem+json` and their body has exactly the RFC7807 keys
  `type`, `title`, `status`, `detail`:
  - `type` is a relative problem identifier (`/problems/not-found` for 404,
    `/problems/forbidden` for 403),
  - `title` is the short human-readable error name,
  - `status` mirrors the HTTP status code,
  - `detail` explains the specific occurrence.
- HTTP status codes are already correct in the initial state and must not
  change: `get_user` answers 200/404, `get_admin_settings` answers
  200/403/404.

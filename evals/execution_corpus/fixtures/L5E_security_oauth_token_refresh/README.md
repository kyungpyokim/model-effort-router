# tokenkeeper

OAuth 2.0-style refresh-token and JWT handling for the profile service,
modeled entirely in process.

Run the acceptance checks from the fixture root:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
```

## Fixture metadata

- Case: L5E_security_oauth_token_refresh (implementation, L5, elevated/security)
- Task: Revamp OAuth 2.0 refresh token rotation and JWT signature validation
- Expected initial test outcome: FAIL (pytest exit status 1)
- The security checks fail against the initial state, where `refresh` hands
  back the same refresh token forever (no rotation, no revocation) and
  `verify` accepts any well-formed token body without checking its signature
  or header algorithm. They pass only after rotation/revocation and real
  HS256 signature validation are implemented.

## Offline contract

The fixture runs fully offline with a deterministic in-process mock provider
(`oauth_provider.MockProvider`) — no live OAuth provider, no external
network, no wall-clock or randomness in the token lifecycle (refresh tokens
are numbered `refresh-0001`, `refresh-0002`, ...). All tests are
deterministic.

## Contracts

- `jwt_tokens.sign(claims, secret)` serializes claims into
  `header.payload.signature` with base64url segments and an HS256 HMAC
  signature.
- `jwt_tokens.verify(token, secret)` returns the claims only when the header
  algorithm is pinned to `HS256` and the signature matches a fresh HS256 HMAC
  over `header.payload` under `secret`; tampered payloads, foreign
  signatures, and non-HS256 headers must raise `ValueError`.
- `MockProvider.issue_refresh_token(client_id)` mints a deterministic,
  unique refresh token bound to the client.
- `MockProvider.refresh(refresh_token)` exchanges a valid token for a new
  access token AND rotates the refresh token: the used token is revoked
  (reuse raises `ValueError`) and a fresh unused token is returned. Concurrent
  refresh attempts with the same token must have exactly one winner.
- Unknown or revoked refresh tokens always raise `ValueError`.

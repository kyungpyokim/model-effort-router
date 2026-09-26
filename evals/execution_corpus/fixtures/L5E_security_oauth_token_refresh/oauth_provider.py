"""Local mock OAuth provider: refresh tokens with in-memory state, no network."""
from __future__ import annotations

import threading

import jwt_tokens

SIGNING_SECRET = b"fixture-signing-secret"


class MockProvider:
    """Issues refresh tokens and exchanges them for access tokens.

    State lives entirely in memory: issued tokens per client, revoked
    tokens, and a monotonic serial that keeps token names deterministic.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._issued: dict[str, str] = {}
        self._revoked: set[str] = set()
        self._serial = 0

    def issue_refresh_token(self, client_id: str) -> str:
        """Mint a deterministic refresh token bound to a client."""
        with self._lock:
            self._serial += 1
            token = f"refresh-{self._serial:04d}"
            self._issued[token] = client_id
            return token

    def refresh(self, refresh_token: str) -> dict:
        """Exchange a refresh token for a new access token."""
        with self._lock:
            if refresh_token not in self._issued or refresh_token in self._revoked:
                raise ValueError("invalid refresh token")
            client_id = self._issued[refresh_token]
            access_token = jwt_tokens.sign(
                {"sub": client_id, "scope": "profile.read"}, SIGNING_SECRET
            )
            return {"access_token": access_token, "refresh_token": refresh_token}

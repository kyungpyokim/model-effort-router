"""Minimal JSON Web Token helpers for the fixture (offline, stdlib only)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json

HEADER = {"alg": "HS256", "typ": "JWT"}


def _b64url_encode(data: bytes) -> str:
    """Base64url-encode bytes without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    """Decode an unpadded base64url string back to bytes."""
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def sign(claims: dict, secret: bytes) -> str:
    """Serialize claims into an HS256-signed token."""
    header = _b64url_encode(json.dumps(HEADER, sort_keys=True).encode("utf-8"))
    payload = _b64url_encode(json.dumps(claims, sort_keys=True).encode("utf-8"))
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = hmac.new(secret, signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64url_encode(signature)}"


def verify(token: str, secret: bytes) -> dict:
    """Return the claims carried by the token."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("malformed token")
    header, payload, signature = parts
    if not signature:
        raise ValueError("missing signature")
    return json.loads(_b64url_decode(payload))

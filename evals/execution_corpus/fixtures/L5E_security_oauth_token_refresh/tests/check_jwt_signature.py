"""Acceptance checks: JWT signature validation must be real."""
from __future__ import annotations

import base64
import json

import pytest

import jwt_tokens

SECRET = b"fixture-signing-secret"
FOREIGN_SECRET = b"attacker-guess"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def _assemble(header: dict, payload: dict, signature: str) -> str:
    head = _b64url(json.dumps(header, sort_keys=True).encode("utf-8"))
    body = _b64url(json.dumps(payload, sort_keys=True).encode("utf-8"))
    return f"{head}.{body}.{signature}"


def test_sign_then_verify_round_trip() -> None:
    claims = {"sub": "u1", "scope": "profile.read"}
    assert jwt_tokens.verify(jwt_tokens.sign(claims, SECRET), SECRET) == claims


def test_sign_produces_three_non_empty_segments() -> None:
    parts = jwt_tokens.sign({"sub": "u1"}, SECRET).split(".")
    assert len(parts) == 3 and all(parts), f"bad token layout: {parts}"


def test_verify_rejects_a_malformed_token() -> None:
    with pytest.raises(ValueError):
        jwt_tokens.verify("onlyonesegment", SECRET)


def test_verify_rejects_a_token_without_a_signature() -> None:
    token = _assemble(jwt_tokens.HEADER, {"sub": "u1"}, "")
    with pytest.raises(ValueError):
        jwt_tokens.verify(token, SECRET)


def test_verify_rejects_tampered_claims() -> None:
    token = jwt_tokens.sign({"sub": "u1", "scope": "profile.read"}, SECRET)
    header, payload, signature = token.split(".")
    claims = json.loads(_decode(payload))
    claims["scope"] = "profile.admin"
    forged = _assemble(json.loads(_decode(header)), claims, signature)
    with pytest.raises(ValueError):
        jwt_tokens.verify(forged, SECRET)


def test_verify_rejects_a_signature_from_another_secret() -> None:
    token = jwt_tokens.sign({"sub": "u1"}, FOREIGN_SECRET)
    with pytest.raises(ValueError):
        jwt_tokens.verify(token, SECRET)


def test_verify_rejects_an_unpinned_algorithm() -> None:
    forged = _assemble(
        {"alg": "none", "typ": "JWT"},
        {"sub": "attacker", "scope": "profile.admin"},
        "forged-signature",
    )
    with pytest.raises(ValueError):
        jwt_tokens.verify(forged, SECRET)

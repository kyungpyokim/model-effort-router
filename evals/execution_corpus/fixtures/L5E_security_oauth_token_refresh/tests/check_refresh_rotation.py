"""Acceptance checks: refresh-token rotation, reuse rejection, concurrency."""
from __future__ import annotations

import threading

import pytest

import jwt_tokens
import oauth_provider


def test_refresh_rotates_the_refresh_token() -> None:
    provider = oauth_provider.MockProvider()
    original = provider.issue_refresh_token("client-a")
    rotated = provider.refresh(original)["refresh_token"]
    assert rotated != original, "refresh must issue a new refresh token"


def test_original_token_is_rejected_after_rotation() -> None:
    provider = oauth_provider.MockProvider()
    original = provider.issue_refresh_token("client-a")
    provider.refresh(original)
    with pytest.raises(ValueError):
        provider.refresh(original)


def test_rotated_token_still_refreshes() -> None:
    provider = oauth_provider.MockProvider()
    first = provider.issue_refresh_token("client-a")
    second = provider.refresh(first)["refresh_token"]
    third = provider.refresh(second)["refresh_token"]
    assert third not in (first, second)


def test_refresh_returns_a_verifiable_access_token() -> None:
    provider = oauth_provider.MockProvider()
    token = provider.issue_refresh_token("client-a")
    access = provider.refresh(token)["access_token"]
    assert jwt_tokens.verify(access, oauth_provider.SIGNING_SECRET) == {
        "sub": "client-a",
        "scope": "profile.read",
    }


def test_unknown_refresh_token_is_rejected() -> None:
    provider = oauth_provider.MockProvider()
    with pytest.raises(ValueError):
        provider.refresh("refresh-9999")


def test_concurrent_refresh_has_exactly_one_winner() -> None:
    """Two threads race the same token: rotation must allow one winner only."""
    provider = oauth_provider.MockProvider()
    original = provider.issue_refresh_token("client-a")
    start = threading.Barrier(3, timeout=10)
    outcomes: list[tuple[str, str | None]] = []

    def exchange() -> None:
        start.wait()
        try:
            outcomes.append(("ok", provider.refresh(original)["refresh_token"]))
        except ValueError:
            outcomes.append(("rejected", None))

    threads = [threading.Thread(target=exchange, daemon=True) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(timeout=10)
    assert not any(thread.is_alive() for thread in threads), "refresh workers must finish"

    winners = [token for status, token in outcomes if status == "ok"]
    rejected = sum(1 for status, _ in outcomes if status == "rejected")
    assert len(winners) == 1 and rejected == 1, (
        f"exactly one concurrent refresh may win the rotation: {outcomes}"
    )
    assert winners[0] != original

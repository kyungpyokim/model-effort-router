"""Acceptance checks: RFC7807 problem-details response envelope."""
from __future__ import annotations

import api

PROBLEM_KEYS = {"type", "title", "status", "detail"}


def test_success_body_drops_the_legacy_envelope() -> None:
    body = api.get_user("u1").body
    assert body == {"id": "u1", "name": "ada", "role": "admin"}, (
        f"success body must be the bare resource, got {body}"
    )


def test_not_found_uses_problem_json_media_type() -> None:
    response = api.get_user("ghost")
    assert response.content_type == "application/problem+json", (
        f"404 must use problem+json, got {response.content_type!r}"
    )


def test_not_found_body_is_problem_details() -> None:
    body = api.get_user("ghost").body
    assert set(body) == PROBLEM_KEYS, f"404 body must be RFC7807 fields, got {sorted(body)}"
    assert body["type"] == "/problems/not-found"
    assert body["status"] == 404
    assert body["detail"]


def test_forbidden_uses_problem_json_media_type() -> None:
    response = api.get_admin_settings("u2")
    assert response.content_type == "application/problem+json", (
        f"403 must use problem+json, got {response.content_type!r}"
    )


def test_forbidden_body_is_problem_details() -> None:
    body = api.get_admin_settings("u2").body
    assert set(body) == PROBLEM_KEYS, f"403 body must be RFC7807 fields, got {sorted(body)}"
    assert body["type"] == "/problems/forbidden"
    assert body["status"] == 403
    assert body["detail"]


def test_success_status_is_200() -> None:
    assert api.get_user("u1").status == 200


def test_success_content_type_is_plain_json() -> None:
    assert api.get_user("u1").content_type == "application/json"


def test_not_found_status_is_404() -> None:
    assert api.get_user("ghost").status == 404


def test_forbidden_status_is_403() -> None:
    assert api.get_admin_settings("u2").status == 403


def test_unknown_user_on_the_admin_endpoint_is_404() -> None:
    assert api.get_admin_settings("ghost").status == 404

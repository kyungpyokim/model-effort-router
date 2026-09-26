"""User-profile API still speaking the legacy data/error response envelope."""
from __future__ import annotations

USERS = {
    "u1": {"id": "u1", "name": "ada", "role": "admin"},
    "u2": {"id": "u2", "name": "lin", "role": "user"},
}


class Response:
    """One HTTP-ish response: status, JSON body, and content type."""

    def __init__(self, status: int, body: dict, content_type: str) -> None:
        self.status = status
        self.body = body
        self.content_type = content_type


def get_user(user_id: str) -> Response:
    """Return one user, or an error envelope when the id is unknown."""
    user = USERS.get(user_id)
    if user is None:
        return Response(
            404,
            {"data": None, "error": {"code": "not_found", "message": f"user {user_id} not found"}},
            "application/json",
        )
    return Response(200, {"data": user, "error": None}, "application/json")


def get_admin_settings(user_id: str) -> Response:
    """Return admin settings, or an error envelope for non-admin users."""
    user = USERS.get(user_id)
    if user is None:
        return Response(
            404,
            {"data": None, "error": {"code": "not_found", "message": f"user {user_id} not found"}},
            "application/json",
        )
    if user["role"] != "admin":
        return Response(
            403,
            {"data": None, "error": {"code": "forbidden", "message": "admin role required"}},
            "application/json",
        )
    return Response(200, {"data": {"theme": "dark", "retention_days": 30}, "error": None}, "application/json")

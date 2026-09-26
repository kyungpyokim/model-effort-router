"""Shared user-profile record for the ten profile services."""
from __future__ import annotations


class UserProfileDTO:
    """A raw upstream profile record handed to the profile services."""

    def __init__(self, record: dict) -> None:
        self.record = dict(record)

    @property
    def user_id(self) -> str:
        return str(self.record.get("id", ""))

    def to_dict(self) -> dict:
        return {
            "id": self.user_id,
            "name": self.record.get("name", ""),
            "source": self.record.get("source", "unknown"),
        }

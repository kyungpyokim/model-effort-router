"""Service service_04 — build tagged user profiles."""
import models


def build_profile(record: dict) -> dict:
    """Copy a raw record into a tagged profile dictionary."""
    profile = models.UserProfileDTO(record).to_dict()
    profile["source"] = "service_04"
    return profile

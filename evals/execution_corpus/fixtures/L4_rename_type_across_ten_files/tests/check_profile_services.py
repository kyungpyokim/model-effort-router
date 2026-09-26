"""Behavior checks: all ten services keep building profile dictionaries."""
from __future__ import annotations

import service_01
import service_02
import service_03
import service_04
import service_05
import service_06
import service_07
import service_08
import service_09
import service_10

SERVICES = {
    "service_01": service_01,
    "service_02": service_02,
    "service_03": service_03,
    "service_04": service_04,
    "service_05": service_05,
    "service_06": service_06,
    "service_07": service_07,
    "service_08": service_08,
    "service_09": service_09,
    "service_10": service_10,
}


def test_every_service_builds_a_tagged_profile() -> None:
    for name, module in SERVICES.items():
        profile = module.build_profile({"id": "u1", "name": "ada"})
        assert profile == {"id": "u1", "name": "ada", "source": name}, (
            f"{name} built {profile}"
        )


def test_build_profile_does_not_mutate_the_input_record() -> None:
    record = {"id": "u7", "name": "grace"}
    for module in SERVICES.values():
        module.build_profile(record)
    assert record == {"id": "u7", "name": "grace"}

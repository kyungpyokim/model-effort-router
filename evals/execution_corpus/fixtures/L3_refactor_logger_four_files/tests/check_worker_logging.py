"""Acceptance checks: all four worker handlers share the structured log format."""
import json

import pytest

import audit_handler
import email_handler
import sms_handler
import webhook_handler

HANDLERS = (audit_handler, email_handler, sms_handler, webhook_handler)
HANDLER_IDS = [module.HANDLER for module in HANDLERS]


def standard_record(job: dict, module) -> str:
    """The structured record every handler must emit for one job."""
    return json.dumps(
        {
            "event": job["event"],
            "handler": module.HANDLER,
            "level": job.get("level", "info"),
        },
        sort_keys=True,
    )


@pytest.mark.parametrize("module", HANDLERS, ids=HANDLER_IDS)
def test_emits_the_standard_record(module) -> None:
    job = {"event": "job.finished"}
    assert module.handle(job) == standard_record(job, module)


@pytest.mark.parametrize("module", HANDLERS, ids=HANDLER_IDS)
def test_carries_an_explicit_level(module) -> None:
    job = {"event": "job.failed", "level": "error"}
    assert module.handle(job) == standard_record(job, module)

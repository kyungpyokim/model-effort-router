"""Acceptance checks: the date-parse helper contract from the fixture README."""
import datetime

import pytest

import utils


def test_parse_date_returns_a_date() -> None:
    from utils import parse_date

    assert parse_date("2026-09-26") == datetime.date(2026, 9, 26)


def test_parse_date_accepts_leap_day() -> None:
    from utils import parse_date

    assert parse_date("2000-02-29") == datetime.date(2000, 2, 29)


def test_parse_date_rejects_impossible_dates() -> None:
    from utils import parse_date

    for value in ("2026-02-30", "09/26/2026", "not-a-date"):
        with pytest.raises(ValueError):
            parse_date(value)


def test_existing_slugify_still_works() -> None:
    assert utils.slugify("Hello, World!") == "hello-world"

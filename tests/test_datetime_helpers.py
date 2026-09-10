"""Tests for the shared date/timestamp helpers (DUP-005, PLAT-001)."""

from __future__ import annotations

from datetime import datetime
from random import Random

import pytest

from ton.generators._datetime import _parse_iso
from ton.generators.date import DateGenerator
from ton.generators.timestamp_unix import TimestampUnixGenerator


@pytest.mark.parametrize("second", [58, 59])
def test_full_date_span_upper_draw_stays_in_bounds(second) -> None:
    """REL-044: rounding a centuries-long span must never add a second."""

    class UpperEndpoint(Random):
        def randint(self, a, b):
            return b

    maximum = f"9999-12-31T23:59:{second}.999999"
    generator = DateGenerator()
    prepared = generator.prepare({"minValue": "0001-01-01", "maxValue": maximum})
    value = generator.generate(prepared, UpperEndpoint())
    assert datetime.fromisoformat(value) <= datetime.fromisoformat(maximum)
    assert value == f"9999-12-31 23:59:{second}"


def test_parse_iso_accepts_uppercase_and_lowercase_zulu() -> None:
    assert _parse_iso("2024-01-01T00:00:00Z").isoformat() == "2024-01-01T00:00:00+00:00"
    assert _parse_iso("2024-01-01T00:00:00z").isoformat() == "2024-01-01T00:00:00+00:00"


def test_parse_iso_accepts_compact_date() -> None:
    assert _parse_iso("20240131").isoformat() == "2024-01-31T00:00:00"


def test_parse_iso_accepts_hour_only_offset() -> None:
    assert _parse_iso("2024-01-01T00:00:00+05").isoformat() == "2024-01-01T00:00:00+05:00"


def test_parse_iso_accepts_full_form() -> None:
    assert _parse_iso("2024-01-01T00:00:00+05:00").isoformat() == "2024-01-01T00:00:00+05:00"


def test_parse_iso_accepts_zulu_suffix() -> None:
    parsed = _parse_iso("2024-01-01T00:00:00Z")
    assert parsed.utcoffset() is not None


def test_timestamp_generator_accepts_zulu_bounds() -> None:
    gen = TimestampUnixGenerator()
    prepared = gen.prepare({"minValue": "2024-01-01T00:00:00Z", "maxValue": "2024-01-01T00:00:00Z"})
    assert prepared.lo_epoch_units == prepared.hi_epoch_units

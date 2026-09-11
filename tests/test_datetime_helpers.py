"""Tests for the shared date/timestamp helpers (DUP-005, PLAT-001)."""

from __future__ import annotations

from datetime import datetime
from random import Random

import pytest

from ton import api
from ton._transforms import TransformResult
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


@pytest.mark.parametrize("mode", ["all", "sample", "audit"])
def test_date_proofs_accept_generated_values_with_an_overflowing_local_upper_bound(mode):
    """REL-061: a distant offset bound must not crash proofs of ordinary draws."""
    spec = {
        "type": "date",
        "minValue": "2024-01-01T00:00:00+02:00",
        "maxValue": "9999-12-31T23:59:59+00:00",
    }
    engine = api.Engine(
        {"rows": 3, "format": "$x$", "types": {"x": spec}},
        seed=42,
        proof_mode=mode,
    )
    assert len(list(engine)) == 3
    assert engine.proof_failure_count == 0


@pytest.mark.parametrize(
    "lo,hi,fmt,good,bad",
    [
        ("9999-12-31T23:00:00+02:00", "9999-12-31T23:59:59Z", "%H:%M", "23:59", "22:59"),
        ("0001-01-01T00:00:00+02:00", "0001-01-01T00:00:00Z", "%H:%M", "02:00", "02:01"),
        ("0001-01-01T00:00:00-02:00", "0001-01-01T03:00:00Z", "%H:%M", "01:00", "01:01"),
        (
            "9999-12-31T23:00:00+02:00",
            "9999-12-31T23:59:59Z",
            "%Y-%m-%d",
            "9999-12-31",
            "9999-12-30",
        ),
        (
            "9999-12-31T23:00:00+02:00",
            "9999-12-31T23:59:59Z",
            "%Y-%m-%d %H:%M:%S%z",
            "9999-12-31 23:59:59+0200",
            "9999-12-31 23:59:59+0000",
        ),
    ],
)
def test_date_proofs_compare_offset_calendar_edges_without_overflow(lo, hi, fmt, good, bad):
    """REL-061: full and partial formats retain exact interval/offset constraints."""
    generator = DateGenerator()
    prepared = generator.prepare({"minValue": lo, "maxValue": hi, "format": fmt})
    assert generator.prove(prepared, TransformResult(good)).ok
    assert not generator.prove(prepared, TransformResult(bad)).ok


def test_date_upper_endpoint_draw_stays_representable_in_the_source_timezone():
    """REL-061: generation and proof use the same representable local interval."""

    class UpperEndpoint(Random):
        def randint(self, a, b):
            return b

    generator = DateGenerator()
    prepared = generator.prepare(
        {
            "minValue": "9999-12-31T23:00:00.123456+02:00",
            "maxValue": "9999-12-31T23:59:59Z",
            "format": "%Y-%m-%d %H:%M:%S.%f%z",
        }
    )
    value = generator.generate(prepared, UpperEndpoint())
    assert value == "9999-12-31 23:59:59.123456+0200"
    assert generator.prove(prepared, TransformResult(value)).ok


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

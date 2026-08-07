"""Tests for the timestamp_unix generator."""

from __future__ import annotations

from datetime import datetime, timezone
from random import Random

import pytest

from ton.generators.timestamp_unix import TimestampUnixGenerator


def _epoch(year: int, month: int = 1, day: int = 1) -> int:
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp())


def test_seconds_within_bounds() -> None:
    gen = TimestampUnixGenerator()
    prepared = gen.prepare({"minValue": "2024-01-01", "maxValue": "2024-12-31"})
    value = int(gen.generate(prepared, Random(0)))
    assert _epoch(2024, 1, 1) <= value <= _epoch(2024, 12, 31) + 86400


def test_millis_multiplies_by_1000() -> None:
    gen = TimestampUnixGenerator()
    prepared = gen.prepare(
        {
            "minValue": "2024-01-01T00:00:00",
            "maxValue": "2024-01-01T00:00:00",
            "unit": "millis",
        }
    )
    value = int(gen.generate(prepared, Random(0)))
    assert value == _epoch(2024, 1, 1) * 1000


@pytest.mark.parametrize(
    ("unit", "minimum", "maximum", "expected"),
    [
        (
            "seconds",
            "1970-01-01T00:00:00.900+00:00",
            "1970-01-01T00:00:01.000+00:00",
            "1",
        ),
        (
            "millis",
            "1970-01-01T00:00:00.900+00:00",
            "1970-01-01T00:00:00.900+00:00",
            "900",
        ),
    ],
)
def test_fractional_bounds_preserve_representable_values(
    unit: str, minimum: str, maximum: str, expected: str
) -> None:
    gen = TimestampUnixGenerator()
    prepared = gen.prepare(
        {
            "minValue": minimum,
            "maxValue": maximum,
            "unit": unit,
        }
    )

    assert gen.generate(prepared, Random(0)) == expected


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        ("1969-12-31T23:59:59.100+00:00", "-900"),
        ("1969-12-31T23:59:59.999+00:00", "-1"),
    ],
)
def test_millis_preserves_pre_epoch_fractions(instant: str, expected: str) -> None:
    gen = TimestampUnixGenerator()
    prepared = gen.prepare({"minValue": instant, "maxValue": instant, "unit": "millis"})

    assert gen.generate(prepared, Random(0)) == expected


@pytest.mark.parametrize("unit", ["seconds", "millis"])
def test_rejects_interval_without_representable_timestamp(unit: str) -> None:
    gen = TimestampUnixGenerator()
    with pytest.raises(ValueError, match="no representable"):
        gen.prepare(
            {
                "minValue": "1970-01-01T00:00:00.000100+00:00",
                "maxValue": "1970-01-01T00:00:00.000900+00:00",
                "unit": unit,
            }
        )


def test_rejects_inverted_bounds() -> None:
    gen = TimestampUnixGenerator()
    with pytest.raises(ValueError):
        gen.prepare({"minValue": "2024-12-31", "maxValue": "2024-01-01"})


def test_rejects_unknown_unit() -> None:
    gen = TimestampUnixGenerator()
    with pytest.raises(ValueError):
        gen.prepare({"minValue": "2024-01-01", "maxValue": "2024-12-31", "unit": "nanos"})


def test_seed_deterministic() -> None:
    gen = TimestampUnixGenerator()
    prepared = gen.prepare({"minValue": "2024-01-01", "maxValue": "2024-12-31"})
    first = gen.generate(prepared, Random(7))
    second = gen.generate(prepared, Random(7))
    assert first == second

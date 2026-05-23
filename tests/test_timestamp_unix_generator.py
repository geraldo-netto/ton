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
    prepared = gen.prepare({
        "minValue": "2024-01-01T00:00:00",
        "maxValue": "2024-01-01T00:00:00",
        "unit": "millis",
    })
    value = int(gen.generate(prepared, Random(0)))
    assert value == _epoch(2024, 1, 1) * 1000


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
    assert gen.generate(prepared, Random(7)) == gen.generate(prepared, Random(7))

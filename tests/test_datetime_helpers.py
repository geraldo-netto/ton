"""Tests for the shared date/timestamp helpers (DUP-005, PLAT-001)."""

from __future__ import annotations

from ton.generators._datetime import _normalize_iso, _parse_iso
from ton.generators.timestamp_unix import TimestampUnixGenerator


def test_normalize_iso_rewrites_trailing_zulu() -> None:
    assert _normalize_iso("2024-01-01T00:00:00Z") == "2024-01-01T00:00:00+00:00"
    assert _normalize_iso("2024-01-01T00:00:00z") == "2024-01-01T00:00:00+00:00"


def test_normalize_iso_expands_compact_date() -> None:
    assert _normalize_iso("20240131") == "2024-01-31"


def test_normalize_iso_pads_hour_only_offset() -> None:
    assert _normalize_iso("2024-01-01T00:00:00+05") == "2024-01-01T00:00:00+05:00"


def test_normalize_iso_leaves_full_form_untouched() -> None:
    assert _normalize_iso("2024-01-01T00:00:00+05:00") == "2024-01-01T00:00:00+05:00"


def test_parse_iso_accepts_zulu_suffix() -> None:
    parsed = _parse_iso("2024-01-01T00:00:00Z")
    assert parsed.utcoffset() is not None


def test_timestamp_generator_accepts_zulu_bounds() -> None:
    gen = TimestampUnixGenerator()
    prepared = gen.prepare({"minValue": "2024-01-01T00:00:00Z", "maxValue": "2024-01-01T00:00:00Z"})
    assert prepared.lo_epoch_units == prepared.hi_epoch_units

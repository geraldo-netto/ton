"""Shared datetime helpers for the ``date`` / ``timestamp_unix`` generators.

Both generators parse ISO ``minValue`` / ``maxValue`` bounds, check the
ordering, compute the span in seconds, and draw a uniform offset within
it. Extracting that idiom keeps the "uniform instant in ``[lo, hi]``"
logic in one place (DUP-005).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from random import Random
from typing import Any

from .base import require_min_le_max


def parse_iso_bounds(
    type_name: str,
    spec: Mapping[str, Any],
    *,
    as_utc: bool = False,
) -> tuple[datetime, datetime]:
    """Parse ``minValue`` / ``maxValue`` and return the ordered ``(lo, hi)``.

    When ``as_utc`` is set, naive datetimes are pinned to UTC before the
    comparison so epoch math downstream is consistent.
    """
    lo = _parse_iso(spec["minValue"])
    hi = _parse_iso(spec["maxValue"])
    if as_utc:
        lo = _to_utc(lo)
        hi = _to_utc(hi)
    require_min_le_max(type_name, lo, hi)
    return lo, hi


def duration_seconds(lo: datetime, hi: datetime) -> int:
    """Return the whole-second span between ``lo`` and ``hi``."""
    delta = hi - lo
    return delta.days * 86_400 + delta.seconds


def uniform_offset_seconds(rng: Random, span: int) -> int:
    """Return a uniform offset in ``[0, span]`` (0 when the span is empty)."""
    return rng.randint(0, span) if span > 0 else 0


def _parse_iso(value: Any) -> datetime:
    """Parse ISO bounds, allowing surrounding whitespace and lowercase Zulu."""
    text = str(value).strip()
    if text.endswith("z"):
        text = f"{text[:-1]}Z"
    return datetime.fromisoformat(text)


def _to_utc(value: datetime) -> datetime:
    """Treat naive datetimes as UTC so epoch math is consistent."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value

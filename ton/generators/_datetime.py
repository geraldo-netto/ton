"""Shared datetime helpers for the ``date`` / ``timestamp_unix`` generators.

Both generators parse ISO ``minValue`` / ``maxValue`` bounds, check the
ordering, compute the span in seconds, and draw a uniform offset within
it. Extracting that idiom keeps the "uniform instant in ``[lo, hi]``"
logic in one place (DUP-005) and gives ISO parsing a single home for the
3.10-portability fix (PLAT-001).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timezone
from random import Random
from typing import Any

from .base import require_min_le_max

#: Compact date ``YYYYMMDD`` (no separators), which 3.10 fromisoformat rejects.
_COMPACT_DATE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
#: Trailing timezone offset without minutes, e.g. ``+05`` / ``-0530`` tails.
_BARE_OFFSET = re.compile(r"([+-]\d{2})$")


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
    return int((hi - lo).total_seconds())


def uniform_offset_seconds(rng: Random, span: int) -> int:
    """Return a uniform offset in ``[0, span]`` (0 when the span is empty)."""
    return rng.randint(0, span) if span > 0 else 0


def _parse_iso(value: Any) -> datetime:
    return datetime.fromisoformat(_normalize_iso(str(value)))


def _normalize_iso(text: str) -> str:
    """Rewrite common ISO 8601 forms 3.10's ``fromisoformat`` rejects (PLAT-001).

    3.11+ accepts a trailing ``Z``, compact ``YYYYMMDD`` dates, and
    hour-only offsets like ``+05``; 3.10 does not. Normalize those so a
    config that works on 3.11+ also parses on the minimum supported 3.10.
    """
    text = text.strip()
    compact = _COMPACT_DATE.match(text)
    if compact:
        return f"{compact.group(1)}-{compact.group(2)}-{compact.group(3)}"
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"
    return _BARE_OFFSET.sub(r"\1:00", text)


def _to_utc(value: datetime) -> datetime:
    """Treat naive datetimes as UTC so epoch math is consistent."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value

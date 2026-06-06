"""Unix epoch timestamp generator.

Same bounds semantics as the ``date`` type but emits epoch seconds
(or milliseconds) instead of a formatted string. Useful for log
ingestion fixtures where the receiver expects numeric timestamps.

Spec fields::

    {
      "type":     "timestamp_unix",
      "minValue": "2000-01-01",      // ISO 8601, date or datetime
      "maxValue": "2030-12-31T23:59:59",
      "unit":     "seconds"          // seconds (default) | millis
    }
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from random import Random
from typing import Any

from .base import Generator, require_min_le_max

_UNIT_MULTIPLIERS = {"seconds": 1, "millis": 1000}


@dataclass(frozen=True)
class TimestampUnixSpec:
    lo_epoch_seconds: int
    span_seconds: int
    multiplier: int  # 1 for seconds, 1000 for millis


class TimestampUnixGenerator(Generator):
    """Uniform epoch timestamp in ``[minValue, maxValue]``."""

    type_name = "timestamp_unix"

    def prepare(self, spec: Mapping[str, Any]) -> TimestampUnixSpec:
        lo = _to_utc(datetime.fromisoformat(spec["minValue"]))
        hi = _to_utc(datetime.fromisoformat(spec["maxValue"]))
        require_min_le_max("timestamp_unix", lo, hi)
        unit = str(spec.get("unit", "seconds"))
        if unit not in _UNIT_MULTIPLIERS:
            raise ValueError(
                f"timestamp_unix 'unit' must be one of {sorted(_UNIT_MULTIPLIERS)} (got {unit!r})"
            )
        return TimestampUnixSpec(
            lo_epoch_seconds=int(lo.timestamp()),
            span_seconds=int((hi - lo).total_seconds()),
            multiplier=_UNIT_MULTIPLIERS[unit],
        )

    def generate(self, prepared: TimestampUnixSpec, rng: Random) -> str:
        offset = rng.randint(0, prepared.span_seconds) if prepared.span_seconds > 0 else 0
        epoch_seconds = prepared.lo_epoch_seconds + offset
        return str(epoch_seconds * prepared.multiplier)


def _to_utc(value: datetime) -> datetime:
    """Treat naive datetimes as UTC so epoch math is consistent."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value

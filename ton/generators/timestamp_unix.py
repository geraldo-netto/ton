"""Unix epoch timestamp generator.

Same bounds semantics as the ``date`` type but emits epoch seconds
(or milliseconds) instead of a formatted string. Useful for log
ingestion fixtures where the receiver expects numeric timestamps.
``millis`` output is second-resolution epoch time multiplied by 1000,
so generated millisecond values always end in ``000``.

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
from random import Random
from typing import Any

from ._datetime import duration_seconds, parse_iso_bounds, uniform_offset_seconds
from .base import Generator

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
        lo, hi = parse_iso_bounds("timestamp_unix", spec, as_utc=True)
        unit = str(spec.get("unit", "seconds"))
        if unit not in _UNIT_MULTIPLIERS:
            raise ValueError(
                f"timestamp_unix 'unit' must be one of {sorted(_UNIT_MULTIPLIERS)} (got {unit!r})"
            )
        return TimestampUnixSpec(
            lo_epoch_seconds=int(lo.timestamp()),
            span_seconds=duration_seconds(lo, hi),
            multiplier=_UNIT_MULTIPLIERS[unit],
        )

    def generate(self, prepared: TimestampUnixSpec, rng: Random) -> str:
        offset = uniform_offset_seconds(rng, prepared.span_seconds)
        epoch_seconds = prepared.lo_epoch_seconds + offset
        return str(epoch_seconds * prepared.multiplier)

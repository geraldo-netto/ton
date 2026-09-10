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
from datetime import UTC, datetime
from random import Random
from typing import Any

from .._contracts import Generator
from .._proof import ProofResult, proof_result
from .._transforms import TransformResult
from ._datetime import parse_iso_bounds

_UNIT_MULTIPLIERS = {"seconds": 1, "millis": 1000}


@dataclass(frozen=True)
class TimestampUnixSpec:
    lo_epoch_units: int
    hi_epoch_units: int


class TimestampUnixGenerator(Generator):
    """Uniform epoch timestamp in ``[minValue, maxValue]``."""

    type_name = "timestamp_unix"

    def prepare(self, spec: Mapping[str, Any], context: Any = None) -> TimestampUnixSpec:
        lo, hi = parse_iso_bounds("timestamp_unix", spec, as_utc=True)
        unit = str(spec.get("unit", "seconds"))
        if unit not in _UNIT_MULTIPLIERS:
            raise ValueError(
                f"timestamp_unix 'unit' must be one of {sorted(_UNIT_MULTIPLIERS)} (got {unit!r})"
            )
        multiplier = _UNIT_MULTIPLIERS[unit]
        lo_epoch_units = _ceil_epoch_units(lo, multiplier)
        hi_epoch_units = _floor_epoch_units(hi, multiplier)
        if lo_epoch_units > hi_epoch_units:
            raise ValueError(f"timestamp_unix bounds contain no representable {unit} timestamp")
        return TimestampUnixSpec(lo_epoch_units=lo_epoch_units, hi_epoch_units=hi_epoch_units)

    def generate(self, prepared: TimestampUnixSpec, rng: Random) -> str:
        return str(rng.randint(prepared.lo_epoch_units, prepared.hi_epoch_units))

    def prove(self, prepared: TimestampUnixSpec, result: TransformResult) -> ProofResult:
        try:
            value = int(result.value)
        except ValueError:
            return proof_result(False, "value is not a Unix timestamp")
        return proof_result(
            prepared.lo_epoch_units <= value <= prepared.hi_epoch_units,
            "timestamp is outside its bounds",
        )


def _epoch_microseconds(value: datetime) -> int:
    delta = value - datetime(1970, 1, 1, tzinfo=UTC)
    return ((delta.days * 86400 + delta.seconds) * 1_000_000) + delta.microseconds


def _ceil_epoch_units(value: datetime, multiplier: int) -> int:
    numerator = _epoch_microseconds(value) * multiplier
    return -(-numerator // 1_000_000)


def _floor_epoch_units(value: datetime, multiplier: int) -> int:
    return _epoch_microseconds(value) * multiplier // 1_000_000

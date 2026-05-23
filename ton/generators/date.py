"""Date / datetime value generator.

Replaces the v1 idiom of stitching dates out of six independent integer
fields (which lets the generator emit Feb 30, Apr 31, ...) with a
single calendar-aware generator that draws a real ``datetime`` between
``minValue`` and ``maxValue`` and formats it with ``strftime``.

Spec fields::

    {
      "type":      "date",
      "minValue":  "1900-01-01",         // ISO 8601, date or datetime
      "maxValue":  "2050-12-31T23:59:59",
      "format":    "%Y-%m-%d %H:%M:%S"   // optional, defaults to ISO
    }
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from random import Random
from typing import Any

from .base import Generator

_DEFAULT_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass(frozen=True)
class DateSpec:
    """Prepared spec: ISO bounds parsed once, ready for fast row draws."""

    lo: datetime
    span_seconds: int
    fmt: str


class DateGenerator(Generator):
    """Uniform datetime in ``[minValue, maxValue]`` formatted via ``strftime``."""

    type_name = "date"

    def prepare(self, spec: Mapping[str, Any]) -> DateSpec:
        lo = datetime.fromisoformat(spec["minValue"])
        hi = datetime.fromisoformat(spec["maxValue"])
        if hi < lo:
            raise ValueError("date generator: maxValue must be >= minValue")
        return DateSpec(
            lo=lo,
            span_seconds=int((hi - lo).total_seconds()),
            fmt=spec.get("format", _DEFAULT_FORMAT),
        )

    def generate(self, prepared: DateSpec, rng: Random) -> str:
        offset = rng.randint(0, prepared.span_seconds) if prepared.span_seconds > 0 else 0
        moment = prepared.lo + timedelta(seconds=offset)
        return moment.strftime(prepared.fmt)

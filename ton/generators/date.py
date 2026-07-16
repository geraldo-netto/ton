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

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from random import Random
from typing import Any

from ._datetime import duration_seconds, parse_iso_bounds, uniform_offset_seconds
from .base import Generator

_DEFAULT_FORMAT = "%Y-%m-%d %H:%M:%S"

#: GNU/Windows strftime flag directives (``%-d``, ``%_d``, ``%0d``,
#: ``%^b``, ``%#d``) that are not portable across the supported OS matrix
#: -- glibc-only no-pad/space-pad and Windows case flags (PLAT-002).
_NON_PORTABLE_DIRECTIVE = re.compile(r"%[-_0^#]")


@dataclass(frozen=True)
class DateSpec:
    """Prepared spec: ISO bounds parsed once, ready for fast row draws."""

    lo: datetime
    span_seconds: int
    fmt: str


class DateGenerator(Generator):
    """Uniform datetime in ``[minValue, maxValue]`` formatted via ``strftime``."""

    type_name = "date"

    def prepare(self, spec: Mapping[str, Any], context: Any = None) -> DateSpec:
        lo, hi = parse_iso_bounds("date", spec)
        fmt = spec.get("format", _DEFAULT_FORMAT)
        _validate_format(fmt)
        return DateSpec(
            lo=lo,
            span_seconds=duration_seconds(lo, hi),
            fmt=fmt,
        )

    def generate(self, prepared: DateSpec, rng: Random) -> str:
        offset = uniform_offset_seconds(rng, prepared.span_seconds)
        moment = prepared.lo + timedelta(seconds=offset)
        return moment.strftime(prepared.fmt)


def _validate_format(fmt: Any) -> None:
    """Reject non-portable strftime directives at prepare time (PLAT-002)."""
    if not isinstance(fmt, str):
        raise ValueError("date 'format' must be a string")
    # Drop literal ``%%`` first so ``%%-d`` (a literal '%-d') is not
    # mistaken for the non-portable ``%-`` flag.
    match = _NON_PORTABLE_DIRECTIVE.search(fmt.replace("%%", ""))
    if match:
        raise ValueError(
            f"date 'format' uses non-portable directive {match.group()!r}; "
            "flags like %-d / %_d / %0d / %^b / %#d differ across platforms"
        )

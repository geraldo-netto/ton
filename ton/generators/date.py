"""Date / datetime value generator.

Replaces the v1 idiom of stitching dates out of six independent integer
fields (which lets the generator emit Feb 30, Apr 31, ...) with a
single calendar-aware generator that draws a real ``datetime`` between
``minValue`` and ``maxValue`` and formats it deterministically.

Spec fields::

    {
      "type":      "date",
      "minValue":  "1900-01-01",         // ISO 8601, date or datetime
      "maxValue":  "2050-12-31T23:59:59",
      "format":    "%Y-%m-%d %H:%M:%S"   // optional, defaults to ISO
    }
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from random import Random
from typing import Any

from .._contracts import Generator
from .._proof import ProofResult, proof_result
from .._transforms import TransformResult
from ._datetime import duration_seconds, parse_iso_bounds, uniform_offset_seconds

_DEFAULT_FORMAT = "%Y-%m-%d %H:%M:%S"

_PORTABLE_DIRECTIVES = frozenset("aAbBcdHIjmMpSUwWxXyYzZf%")

_WEEKDAY_ABBR = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_WEEKDAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
_MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

_DIRECTIVE_PATTERNS = {
    "a": rf"(?:{'|'.join(_WEEKDAY_ABBR)})",
    "A": rf"(?:{'|'.join(_WEEKDAY_NAMES)})",
    "b": rf"(?:{'|'.join(_MONTH_ABBR)})",
    "B": rf"(?:{'|'.join(_MONTH_NAMES)})",
    "c": (
        rf"(?:{'|'.join(_WEEKDAY_ABBR)}) (?:{'|'.join(_MONTH_ABBR)}) "
        r"(?: [1-9]|[12]\d|3[01]) (?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d \d{4}"
    ),
    "d": r"(?:0[1-9]|[12]\d|3[01])",
    "H": r"(?:[01]\d|2[0-3])",
    "I": r"(?:0[1-9]|1[0-2])",
    "j": r"(?:00[1-9]|0[1-9]\d|[12]\d{2}|3[0-6]\d)",
    "m": r"(?:0[1-9]|1[0-2])",
    "M": r"[0-5]\d",
    "p": r"(?:AM|PM)",
    "S": r"[0-5]\d",
    "U": r"(?:[0-4]\d|5[0-3])",
    "w": r"[0-6]",
    "W": r"(?:[0-4]\d|5[0-3])",
    "x": r"(?:0[1-9]|1[0-2])/(?:0[1-9]|[12]\d|3[01])/\d{2}",
    "X": r"(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d",
    "y": r"\d{2}",
    "Y": r"\d{4}",
    "z": r"(?:[+-]\d{4}(?:\d{2}(?:\.\d{6})?)?)?",
    "Z": r"(?:UTC(?:[+-]\d{2}:\d{2}(?::\d{2}(?:\.\d{6})?)?)?)?",
    "f": r"\d{6}",
    "%": "%",
}

FormatToken = tuple[bool, str]


@dataclass(frozen=True)
class DateSpec:
    """Prepared spec: ISO bounds parsed once, ready for fast row draws."""

    lo: datetime
    hi: datetime
    span_seconds: int
    fmt: str
    format_tokens: tuple[FormatToken, ...]
    value_pattern: re.Pattern[str]


class DateGenerator(Generator):
    """Uniform datetime in ``[minValue, maxValue]`` with portable formatting."""

    type_name = "date"
    config_keys = frozenset(("format", "maxValue", "minValue"))

    def prepare(self, spec: Mapping[str, Any], context: Any = None) -> DateSpec:
        lo, hi = parse_iso_bounds("date", spec)
        hi = _local_upper_bound(lo, hi)
        fmt = spec.get("format", _DEFAULT_FORMAT)
        format_tokens = _tokenize_format(fmt)
        return DateSpec(
            lo=lo,
            hi=hi,
            span_seconds=duration_seconds(lo, hi),
            fmt=fmt,
            format_tokens=format_tokens,
            value_pattern=_compile_pattern(format_tokens),
        )

    def generate(self, prepared: DateSpec, rng: Random) -> str:
        offset = uniform_offset_seconds(rng, prepared.span_seconds)
        moment = prepared.lo + timedelta(seconds=offset)
        return "".join(_format_token(moment, token) for token in prepared.format_tokens)

    def prove(self, prepared: DateSpec, result: TransformResult) -> ProofResult:
        match = prepared.value_pattern.fullmatch(result.value)
        if match is None:
            return proof_result(False, "value does not match the date format")
        constraints = _component_constraints(prepared.format_tokens, match.groups())
        return proof_result(
            constraints is not None and _matches_interval(prepared, constraints),
            "value has inconsistent date components or is outside the configured date interval",
        )


def _local_upper_bound(lo: datetime, hi: datetime) -> datetime:
    """Intersect with representable local dates before converting zones (REL-061).

    Aware datetime comparisons handle UTC instants outside years 1–9999
    without materializing them. Conversion is safe only after intersection.
    Ordered bounds already guarantee the lower endpoint is representable.
    """
    if lo.tzinfo is None:
        return hi
    ceiling = datetime.max.replace(tzinfo=lo.tzinfo)
    return min(hi, ceiling).astimezone(lo.tzinfo)


def _tokenize_format(fmt: Any) -> tuple[FormatToken, ...]:
    """Validate and tokenize the locale-neutral format contract."""
    if not isinstance(fmt, str):
        raise ValueError("date 'format' must be a string")
    tokens: list[FormatToken] = []
    index = 0
    while index < len(fmt):
        if fmt[index] != "%":
            end = fmt.find("%", index)
            end = len(fmt) if end < 0 else end
            tokens.append((False, fmt[index:end]))
            index = end
            continue
        if index + 1 >= len(fmt) or fmt[index + 1] not in _PORTABLE_DIRECTIVES:
            directive = fmt[index : index + 2]
            raise ValueError(f"date 'format' uses non-portable directive {directive!r}")
        tokens.append((True, fmt[index + 1]))
        index += 2
    return tuple(tokens)


def _compile_pattern(tokens: tuple[FormatToken, ...]) -> re.Pattern[str]:
    parts = [
        _DIRECTIVE_PATTERNS[text] if is_directive else re.escape(text)
        for is_directive, text in tokens
    ]
    return re.compile("".join(f"({part})" for part in parts), re.ASCII)


def _format_token(moment: datetime, token: FormatToken) -> str:
    is_directive, text = token
    return _format_directive(moment, text) if is_directive else text


def _component_constraints(
    tokens: tuple[FormatToken, ...], values: tuple[str, ...]
) -> dict[str, str] | None:
    constraints: dict[str, str] = {}
    for (directive, token), value in zip(tokens, values, strict=True):
        if not directive or token == "%":
            continue
        for key, component in _expand_component(token, value):
            if key in constraints and constraints[key] != component:
                return None
            constraints[key] = component
    return constraints


def _expand_component(token: str, value: str) -> tuple[tuple[str, str], ...]:
    if token == "X":
        return tuple(zip("HMS", value.split(":"), strict=True))
    if token == "x":
        return tuple(zip("mdy", value.split("/"), strict=True))
    if token == "c":
        weekday, month, day, clock, year = value.split()
        return (
            ("a", weekday),
            ("b", month),
            ("d", day.zfill(2)),
            ("Y", year),
            *_expand_component("X", clock),
        )
    return ((token, value),)


def _components_match(moment: datetime, constraints: dict[str, str], keys: str) -> bool:
    return all(
        _format_directive(moment, key) == constraints[key] for key in keys if key in constraints
    )


def _numeric_candidates(constraints: dict[str, str], key: str, start: int, stop: int) -> range:
    if key not in constraints:
        return range(start, stop)
    value = int(constraints[key])
    return range(max(start, value), min(stop, value + 1))


def _years(constraints: dict[str, str], start: int, stop: int) -> range:
    if "Y" in constraints or "y" not in constraints:
        return _numeric_candidates(constraints, "Y", start, stop)
    first = start + (int(constraints["y"]) - start) % 100
    return range(first, stop, 100)


def _months(constraints: dict[str, str]) -> range:
    if "m" in constraints:
        return _numeric_candidates(constraints, "m", 1, 13)
    for key, names in (("b", _MONTH_ABBR), ("B", _MONTH_NAMES)):
        if key in constraints:
            month = names.index(constraints[key]) + 1
            return range(month, month + 1)
    return range(1, 13)


def _matching_dates(prepared: DateSpec, constraints: dict[str, str]) -> Iterator[datetime]:
    lo, hi = prepared.lo, prepared.hi
    for year in _years(constraints, lo.year, hi.year + 1):
        moment = datetime(year, 1, 1, tzinfo=lo.tzinfo)
        if not _components_match(moment, constraints, "Yy"):
            continue
        for month in _months(constraints):
            moment = moment.replace(month=month)
            if not _components_match(moment, constraints, "mbB"):
                continue
            for day in _numeric_candidates(
                constraints, "d", 1, calendar.monthrange(year, month)[1] + 1
            ):
                candidate = moment.replace(day=day)
                if lo.date() <= candidate.date() <= hi.date() and _components_match(
                    candidate, constraints, "daAjUwW"
                ):
                    yield candidate


def _matches_interval(prepared: DateSpec, constraints: dict[str, str]) -> bool:
    if not _components_match(prepared.lo, constraints, "zZ"):
        return False
    hours = [
        hour
        for hour in _numeric_candidates(constraints, "H", 0, 24)
        if _components_match(prepared.lo.replace(hour=hour), constraints, "HIp")
    ]
    minutes = [
        minute
        for minute in _numeric_candidates(constraints, "M", 0, 60)
        if _components_match(prepared.lo.replace(minute=minute), constraints, "M")
    ]
    seconds = [
        second
        for second in _numeric_candidates(constraints, "S", 0, 60)
        if _components_match(prepared.lo.replace(second=second), constraints, "S")
    ]
    microsecond = int(constraints["f"]) if "f" in constraints else None
    return any(
        _time_in_bounds(day, prepared, hours, minutes, seconds, microsecond)
        for day in _matching_dates(prepared, constraints)
    )


def _time_in_bounds(
    day: datetime,
    prepared: DateSpec,
    hours: list[int],
    minutes: list[int],
    seconds: list[int],
    microsecond: int | None,
) -> bool:
    lo = max(day, prepared.lo)
    hi = min(day.replace(hour=23, minute=59, second=59, microsecond=999999), prepared.hi)
    for hour in hours:
        if not lo.hour <= hour <= hi.hour:
            continue
        first_minute = lo.minute if hour == lo.hour else 0
        last_minute = hi.minute if hour == hi.hour else 59
        for minute in minutes:
            if not first_minute <= minute <= last_minute:
                continue
            if _second_in_bounds(
                day.replace(hour=hour, minute=minute), lo, hi, seconds, microsecond
            ):
                return True
    return False


def _second_in_bounds(
    moment: datetime, lo: datetime, hi: datetime, seconds: list[int], microsecond: int | None
) -> bool:
    for second in seconds:
        candidate = moment.replace(second=second, microsecond=microsecond or 0)
        if microsecond is None and candidate.replace(microsecond=lo.microsecond) == lo:
            candidate = lo
        if lo <= candidate <= hi:
            return True
    return False


def _format_directive(moment: datetime, directive: str) -> str:
    return _DIRECTIVE_FORMATTERS[directive](moment)


def _format_c_datetime(moment: datetime) -> str:
    return (
        f"{_WEEKDAY_ABBR[moment.weekday()]} {_MONTH_ABBR[moment.month - 1]} "
        f"{moment.day:2d} {moment.hour:02d}:{moment.minute:02d}:{moment.second:02d} "
        f"{moment.year:04d}"
    )


def _week_number(moment: datetime, *, sunday_first: bool) -> int:
    weekday = (moment.weekday() + 1) % 7 if sunday_first else moment.weekday()
    return (moment.timetuple().tm_yday - 1 + 7 - weekday) // 7


def _format_timezone_name(moment: datetime) -> str:
    offset = moment.utcoffset()
    if offset is None:
        return ""
    if offset == timedelta(0):
        return "UTC"
    return f"UTC{_format_utc_offset(moment, colon=True)}"


def _format_utc_offset(moment: datetime, *, colon: bool) -> str:
    offset = moment.utcoffset()
    if offset is None:
        return ""
    total_microseconds = (offset.days * 86_400 + offset.seconds) * 1_000_000 + offset.microseconds
    sign = "+" if total_microseconds >= 0 else "-"
    hours, remainder = divmod(abs(total_microseconds), 3_600_000_000)
    minutes, remainder = divmod(remainder, 60_000_000)
    seconds, microseconds = divmod(remainder, 1_000_000)
    separator = ":" if colon else ""
    rendered = f"{sign}{hours:02d}{separator}{minutes:02d}"
    if seconds or microseconds:
        rendered += f"{separator}{seconds:02d}"
    if microseconds:
        rendered += f".{microseconds:06d}"
    return rendered


_DIRECTIVE_FORMATTERS: dict[str, Callable[[datetime], str]] = {
    "a": lambda moment: _WEEKDAY_ABBR[moment.weekday()],
    "A": lambda moment: _WEEKDAY_NAMES[moment.weekday()],
    "b": lambda moment: _MONTH_ABBR[moment.month - 1],
    "B": lambda moment: _MONTH_NAMES[moment.month - 1],
    "c": _format_c_datetime,
    "d": lambda moment: f"{moment.day:02d}",
    "H": lambda moment: f"{moment.hour:02d}",
    "I": lambda moment: f"{moment.hour % 12 or 12:02d}",
    "j": lambda moment: f"{moment.timetuple().tm_yday:03d}",
    "m": lambda moment: f"{moment.month:02d}",
    "M": lambda moment: f"{moment.minute:02d}",
    "p": lambda moment: "AM" if moment.hour < 12 else "PM",
    "S": lambda moment: f"{moment.second:02d}",
    "U": lambda moment: f"{_week_number(moment, sunday_first=True):02d}",
    "w": lambda moment: str((moment.weekday() + 1) % 7),
    "W": lambda moment: f"{_week_number(moment, sunday_first=False):02d}",
    "x": lambda moment: f"{moment.month:02d}/{moment.day:02d}/{moment.year % 100:02d}",
    "X": lambda moment: f"{moment.hour:02d}:{moment.minute:02d}:{moment.second:02d}",
    "y": lambda moment: f"{moment.year % 100:02d}",
    "Y": lambda moment: f"{moment.year:04d}",
    "z": lambda moment: _format_utc_offset(moment, colon=False),
    "Z": _format_timezone_name,
    "f": lambda moment: f"{moment.microsecond:06d}",
    "%": lambda moment: "%",
}

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

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from random import Random
from typing import Any

from .._proof import ProofResult
from .._transforms import TransformResult
from ._datetime import duration_seconds, parse_iso_bounds, uniform_offset_seconds
from .base import Generator, proof_result

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
    proof_format: str | None


class DateGenerator(Generator):
    """Uniform datetime in ``[minValue, maxValue]`` with portable formatting."""

    type_name = "date"

    def prepare(self, spec: Mapping[str, Any], context: Any = None) -> DateSpec:
        lo, hi = parse_iso_bounds("date", spec)
        fmt = spec.get("format", _DEFAULT_FORMAT)
        format_tokens = _tokenize_format(fmt)
        return DateSpec(
            lo=lo,
            hi=hi,
            span_seconds=duration_seconds(lo, hi),
            fmt=fmt,
            format_tokens=format_tokens,
            value_pattern=_compile_pattern(format_tokens),
            proof_format=_proof_parseable_format(lo, fmt, format_tokens),
        )

    def generate(self, prepared: DateSpec, rng: Random) -> str:
        offset = uniform_offset_seconds(rng, prepared.span_seconds)
        moment = prepared.lo + timedelta(seconds=offset)
        return "".join(_format_token(moment, token) for token in prepared.format_tokens)

    def prove(self, prepared: DateSpec, result: TransformResult) -> ProofResult:
        if prepared.value_pattern.fullmatch(result.value) is None:
            return proof_result(False, "value does not match the date format")
        if prepared.proof_format is None:
            return proof_result(True, "")
        try:
            moment = datetime.strptime(result.value, prepared.proof_format)
        except ValueError:
            return proof_result(False, "value is not a valid calendar date")
        moment = _align_proof_timezone(moment, prepared.lo)
        if _render(moment, prepared.format_tokens) != result.value:
            return proof_result(False, "value has inconsistent date components")
        if _has_complete_date(prepared.format_tokens):
            interval_end = moment + _proof_resolution(prepared.format_tokens)
            if interval_end < prepared.lo or moment > prepared.hi:
                return proof_result(False, "value is outside the configured date interval")
        return proof_result(True, "")


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
    return re.compile("".join(parts))


def _format_token(moment: datetime, token: FormatToken) -> str:
    is_directive, text = token
    return _format_directive(moment, text) if is_directive else text


def _render(moment: datetime, tokens: tuple[FormatToken, ...]) -> str:
    return "".join(_format_token(moment, token) for token in tokens)


def _proof_parseable_format(
    sample_moment: datetime,
    fmt: str,
    tokens: tuple[FormatToken, ...],
) -> str | None:
    sample = _render(sample_moment, tokens)
    try:
        parsed = datetime.strptime(sample, fmt)
    except (re.error, ValueError):
        return None
    parsed = _align_proof_timezone(parsed, sample_moment)
    return fmt if _render(parsed, tokens) == sample else None


def _align_proof_timezone(moment: datetime, bound: datetime) -> datetime:
    if moment.tzinfo is None and bound.tzinfo is not None:
        return moment.replace(tzinfo=bound.tzinfo)
    return moment


def _proof_resolution(tokens: tuple[FormatToken, ...]) -> timedelta:
    directives = {text for is_directive, text in tokens if is_directive}
    if "f" in directives:
        return timedelta(0)
    if directives & {"S", "X", "c"}:
        return timedelta(microseconds=999_999)
    if "M" in directives:
        return timedelta(seconds=59, microseconds=999_999)
    if directives & {"H", "I", "p"}:
        return timedelta(minutes=59, seconds=59, microseconds=999_999)
    return timedelta(days=1, microseconds=-1)


def _has_complete_date(tokens: tuple[FormatToken, ...]) -> bool:
    directives = {text for is_directive, text in tokens if is_directive}
    if directives & {"c", "x"}:
        return True
    has_year = bool(directives & {"Y", "y"})
    return has_year and (
        "j" in directives or ("d" in directives and bool(directives & {"m", "b", "B"}))
    )


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

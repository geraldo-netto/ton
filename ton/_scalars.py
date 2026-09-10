"""Dependency-free scalar parsing, formatting, and configuration coercion."""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal
from numbers import Rational
from typing import Any

#: Shape of a plain decimal integer, used to keep :func:`str_to_int` as
#: strict as ``int`` when it falls back to the arbitrary-size path.
_INTEGER_TEXT = re.compile(r"[+-]?\d+")


def int_to_str(value: int) -> str:
    """Render ``value`` in decimal, whatever its size.

    CPython refuses ``str()`` on integers over ``sys.get_int_max_str_digits()``
    (4,300 by default). TON has no digit ceiling, so oversized values fall back
    to an exact ``Decimal`` rendering instead of failing or requiring a
    process-global setting change (SCALE-005). The fast path is unchanged.
    """
    try:
        return str(value)
    except ValueError:
        return format(Decimal(value), "f")


def str_to_int(text: str) -> int:
    """Parse a decimal integer of any size, as strictly as ``int``."""
    try:
        return int(text)
    except ValueError:
        if not _INTEGER_TEXT.fullmatch(text.strip()):
            raise
        return int(Decimal(text))


def pad_with_zero(value: str, width: int) -> str:
    """Left-pad ``value`` with zeros to ``width`` characters."""
    return value.zfill(width)


def require_non_empty_values(spec: Mapping[str, Any]) -> list[Any]:
    """Return ``spec['values']`` after asserting it is a non-empty list.

    Common validator for string-pool, char, and hash generators.
    Raises ``ValueError`` (the config layer translates this to
    ``ConfigError``) so the failure happens at engine construction,
    not on the first row.
    """
    values = spec.get("values")
    if not isinstance(values, list) or not values:
        raise ValueError(
            "'values' must be a non-empty list (got: "
            f"{type(values).__name__ if values is not None else 'missing'})"
        )
    return values


def require_string_tuple(spec: Mapping[str, Any], key: str = "values") -> tuple[str, ...]:
    """Return ``spec[key]`` as a non-empty ``Tuple[str, ...]``.

    Combines the non-empty-list check with the ``tuple(str(v) for v in ...)``
    coercion that was repeated in five generators (string / char / hash /
    weighted / identity). Raises ``ValueError`` on a missing, non-list,
    or empty value.
    """
    raw = spec.get(key)
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            f"{key!r} must be a non-empty list (got: "
            f"{type(raw).__name__ if raw is not None else 'missing'})"
        )
    return tuple(str(v) for v in raw)


_MISSING = object()


def _value_or_default(spec: Mapping[str, Any], key: str, type_name: str, default: Any) -> Any:
    if default is _MISSING:
        if key not in spec:
            raise ValueError(f"{type_name} {key!r} is required")
        return spec[key]
    return spec.get(key, default)


def coerce_int(
    spec: Mapping[str, Any],
    key: str,
    *,
    type_name: str,
    default: Any = _MISSING,
) -> int:
    """Read ``spec[key]`` and coerce to ``int`` with a uniform error message.

    When ``default`` is omitted the key is required; passing any value
    (including ``None``) treats it as optional. Used by integer / decimal
    / char / bytes / text / sequence / uuid generators so their per-field
    coercion + validation surface stays centralized (DUP-006).
    """
    raw = _value_or_default(spec, key, type_name, default)
    if isinstance(raw, bool):
        raise ValueError(f"{type_name} {key!r} must be an integer (got {raw!r})")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, Rational):
        if raw.denominator == 1:
            return int(raw.numerator)
        raise ValueError(f"{type_name} {key!r} must be an integer (got {raw!r})")
    # Check Decimal exactly before int() can truncate it (CFG-024).
    if isinstance(raw, Decimal) and (not raw.is_finite() or raw != raw.to_integral_value()):
        raise ValueError(f"{type_name} {key!r} must be an integer (got {raw!r})")
    if isinstance(raw, float):
        if raw.is_integer():
            return int(raw)
        raise ValueError(f"{type_name} {key!r} must be an integer (got {raw!r})")
    try:
        return str_to_int(raw) if isinstance(raw, str) else int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{type_name} {key!r} must be an integer (got {raw!r})") from exc


def coerce_string(
    spec: Mapping[str, Any],
    key: str,
    *,
    type_name: str,
    default: Any = _MISSING,
) -> str:
    """Read ``spec[key]`` and coerce it to ``str`` with uniform missing-key errors."""
    return str(_value_or_default(spec, key, type_name, default))


def coerce_bool(
    spec: Mapping[str, Any],
    key: str,
    *,
    type_name: str,
    default: Any = _MISSING,
) -> bool:
    """Read a JSON boolean without treating non-empty strings as true."""
    raw = _value_or_default(spec, key, type_name, default)
    if not isinstance(raw, bool):
        raise ValueError(f"{type_name} {key!r} must be a boolean (got {raw!r})")
    return raw


def require_min_le_max(type_name: str, lo: Any, hi: Any) -> None:
    """Raise when ``hi < lo``. Centralizes the bounds check used by the
    integer / decimal / date / timestamp_unix generators (DUP-004).
    """
    if hi < lo:
        raise ValueError(f"{type_name} 'maxValue' ({hi}) must be >= 'minValue' ({lo})")

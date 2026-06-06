"""Config file loading and structural validation.

Per-type validation (e.g. ``minValue <= maxValue``, ``decimals >= 0``,
``values`` non-empty) lives in each :class:`ton.generators.Generator`'s
``prepare`` method and runs when the :class:`ton.engine.Engine` is
constructed. This module is intentionally type-agnostic so the two
validation surfaces cannot drift (TODO REL-011).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from ._template import UndeclaredVariableError, validate_against


class ConfigError(ValueError):
    """Raised when a config file is missing required keys or has wrong types."""


_REQUIRED_TOP_LEVEL = ("rows", "format", "types")

#: Defensive upper bound on row count. Type-specific upper bounds
#: belong to the relevant generator's ``prepare`` method.
MAX_ROWS = 1_000_000_000

#: Documented worst-case rendered row width when every type is set to
#: its own per-field cap (TODO SCALE-002). Worst-case contributions:
#:
#: * ``regex``           -> MAX_LITERAL_REPEAT     (10_000 chars)
#: * ``char``            -> MAX_CHAR_LENGTH        (100_000 chars)
#: * ``bytes`` (hex)     -> 2 x MAX_BYTES_LENGTH   (2_000_000 chars)
#: * ``text`` paragraphs -> MAX_TEXT_COUNT x ~80   (~800_000 chars)
#:
#: A single placeholder can therefore push a row past 2 MB before any
#: global cap fires. Callers that need a hard ceiling should validate
#: against this constant *or* lower the per-field caps in the relevant
#: generator module.
MAX_ROW_WIDTH_GUIDANCE = 2_000_000


def load(path: str | Path) -> dict[str, Any]:
    """Read a JSON config from disk and validate its top-level shape.

    Raises:
        FileNotFoundError: if ``path`` does not exist.
        ConfigError: if required keys are missing, types are wrong, the
            row count exceeds :data:`MAX_ROWS`, or the template
            references variables not declared in ``types``.
        json.JSONDecodeError: if the file is not valid JSON.

    Per-spec field validation (bounds, value lists, ...) is the
    responsibility of the generator and happens when the Engine is
    built; CLI users still see those errors via the exit-code-2 path.
    """
    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open(encoding="utf-8") as fh:
        data = json.load(fh)

    _validate(data)
    return cast(dict[str, Any], data)


def _validate(data: Any) -> None:
    _validate_root(data)
    _validate_rows(data["rows"])
    _validate_format(data["format"])
    _validate_types(data["types"])
    _validate_template_references(data["format"], data["types"])


def _validate_root(data: Any) -> None:
    if not isinstance(data, dict):
        raise ConfigError("Config root must be a JSON object.")
    missing = [key for key in _REQUIRED_TOP_LEVEL if key not in data]
    if missing:
        raise ConfigError(f"Config missing required keys: {missing}")


def _validate_rows(rows: Any) -> None:
    if not isinstance(rows, int) or isinstance(rows, bool) or rows < 0:
        raise ConfigError("'rows' must be a non-negative integer.")
    if rows > MAX_ROWS:
        raise ConfigError(f"'rows' exceeds MAX_ROWS ({MAX_ROWS}).")


def _validate_format(template: Any) -> None:
    if not isinstance(template, str) or not template:
        raise ConfigError("'format' must be a non-empty string.")


def _validate_types(types: Any) -> None:
    if not isinstance(types, dict) or not types:
        raise ConfigError("'types' must be a non-empty object.")
    for name, spec in types.items():
        _validate_type_spec(name, spec)


def _validate_type_spec(name: str, spec: Any) -> None:
    if not isinstance(spec, dict) or "type" not in spec:
        raise ConfigError(f"Type spec {name!r} must be an object with a 'type' field.")
    if not isinstance(spec["type"], str) or not spec["type"]:
        raise ConfigError(f"Type spec {name!r} 'type' must be a non-empty string.")
    transforms = spec.get("transforms", [])
    if not isinstance(transforms, list):
        raise ConfigError(f"Type spec {name!r} 'transforms' must be a list.")
    for index, transform in enumerate(transforms):
        if not isinstance(transform, dict) or "type" not in transform:
            raise ConfigError(
                f"Type spec {name!r} transform {index} must be an object "
                "with a 'type' field."
            )


def _validate_template_references(template: str, types: dict[str, Any]) -> None:
    """Delegate to :func:`ton.template.validate_against` (TODO DEC-002)."""
    try:
        validate_against(template, types.keys())
    except UndeclaredVariableError as exc:
        raise ConfigError(str(exc)) from exc

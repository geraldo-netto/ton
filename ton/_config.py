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
        if not isinstance(spec, dict) or "type" not in spec:
            raise ConfigError(f"Type spec {name!r} must be an object with a 'type' field.")


def _validate_template_references(template: str, types: dict[str, Any]) -> None:
    """Delegate to :func:`ton.template.validate_against` (TODO DEC-002)."""
    try:
        validate_against(template, types.keys())
    except UndeclaredVariableError as exc:
        raise ConfigError(str(exc)) from exc

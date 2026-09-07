"""Config file loading and structural validation.

Per-type validation (e.g. ``minValue <= maxValue``, ``decimals >= 0``,
``values`` non-empty) lives in each :class:`ton.generators.Generator`'s
``prepare`` method and runs when the :class:`ton.engine.Engine` is
constructed. This module is intentionally type-agnostic so the two
validation surfaces cannot drift (REL-011).
"""

from __future__ import annotations

import codecs
import json
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from ._compiler import TemplateError, compile_plan
from ._logging import LogEvent
from ._logging import logger as _logger
from ._registry import ExtensionCatalog
from ._speckeys import unknown_key_message
from ._template import UndeclaredVariableError, validate_against
from .generators.base import str_to_int


class ConfigError(ValueError):
    """Raised when a config file is missing required keys or has wrong types."""


_REQUIRED_TOP_LEVEL = ("rows", "format", "types")
ROOT_KEYS = frozenset((*_REQUIRED_TOP_LEVEL, "encoding", "maxRowWidth"))
_unknown_key_message = unknown_key_message


def load(path: str | Path) -> dict[str, Any]:
    """Read a JSON config from disk and validate its top-level shape.

    Raises:
        FileNotFoundError: if ``path`` does not exist.
        ConfigError: if required keys are missing, types are wrong, the
            row count is invalid, or the template references variables
            not declared in ``types``.
        json.JSONDecodeError: if the file is not valid JSON.

    Per-spec field validation (bounds, value lists, ...) is the
    responsibility of the generator and happens when the Engine is
    built; CLI users still see those errors via the exit-code-2 path.
    """
    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    try:
        with config_path.open(encoding="utf-8") as fh:
            # ``str_to_int`` keeps arbitrarily large JSON integers loadable:
            # the stdlib parser inherits CPython's 4,300-digit conversion
            # ceiling and would fail before structural validation (CFG-006).
            # ``Decimal`` keeps written decimal bounds exact: binary floats
            # silently moved them off the requested interval (CFG-007).
            data = json.load(fh, parse_int=str_to_int, parse_float=Decimal)
    except UnicodeDecodeError as exc:
        raise ConfigError(f"Config file must be valid UTF-8: {exc}") from exc

    validate_structure(data)
    return cast(dict[str, Any], data)


def validate_with_catalog(data: Mapping[str, Any], catalog: ExtensionCatalog) -> None:
    """Validate type and transform references against ``catalog``.

    Also runs each field's ``Generator.prepare`` so per-spec errors
    (bounds, value lists, output caps) surface here rather than only at
    generation time -- otherwise ``--validate`` reports a bad-bounds
    config as valid and the real run fails (CLI-001).
    """
    validate_structure(data)
    generators = catalog.generators()
    transforms = catalog.transforms()
    validators = catalog.validators()
    try:
        compile_plan(
            data,
            registry=generators,
            transforms=transforms,
            validators=validators,
            prepare_all_fields=True,
        )
    except TemplateError as exc:
        raise ConfigError(str(exc)) from exc
    _logger.info(
        "config_validated types=%d",
        len(data["types"]),
        extra={
            "event": LogEvent.CONFIG_VALIDATED.value,
            "types": len(data["types"]),
            "available_types": catalog.list_data_types(),
            "available_transforms": catalog.list_transforms(),
            "available_validators": catalog.list_validators(),
        },
    )


def validate_structure(data: Any) -> None:
    """Validate the config shape shared by file and in-memory entry points."""
    _validate_root(data)
    _validate_rows(data["rows"])
    _validate_format(data["format"])
    _validate_types(data["types"])
    _validate_template_references(data["format"], data["types"])
    _validate_encoding(data)
    _validate_row_width(data)


def _validate_row_width(data: Mapping[str, Any]) -> None:
    if "maxRowWidth" not in data:
        return
    value = data["maxRowWidth"]
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigError("'maxRowWidth' must be a positive integer.")


def row_width_limit(data: Mapping[str, Any]) -> int | None:
    value = data.get("maxRowWidth")
    return int(value) if value is not None else None


def _validate_encoding(data: Mapping[str, Any]) -> None:
    """Validate the optional top-level ``encoding`` output codec (CFG-001)."""
    if "encoding" not in data:
        return
    encoding = data["encoding"]
    if not isinstance(encoding, str):
        raise ConfigError("'encoding' must be a string.")
    try:
        codec = codecs.lookup(encoding)
    except LookupError as exc:
        raise ConfigError(f"'encoding' is not a known codec: {encoding!r}") from exc
    if not getattr(codec, "_is_text_encoding", False):
        raise ConfigError(f"'encoding' must be a text codec: {encoding!r}")


def output_encoding(data: Mapping[str, Any]) -> str:
    """Return the configured output encoding, defaulting to UTF-8 (CFG-001)."""
    encoding = data.get("encoding", "utf-8")
    return encoding if isinstance(encoding, str) else "utf-8"


def _validate_root(data: Any) -> None:
    if not isinstance(data, Mapping):
        raise ConfigError("Config root must be a JSON object.")
    missing = [key for key in _REQUIRED_TOP_LEVEL if key not in data]
    if missing:
        raise ConfigError(f"Config missing required keys: {missing}")
    unknown = set(data) - ROOT_KEYS
    if unknown:
        key = min(unknown)
        raise ConfigError(_unknown_key_message("config", key, ROOT_KEYS))


def _validate_rows(rows: Any) -> None:
    if not isinstance(rows, int) or isinstance(rows, bool) or rows < 0:
        raise ConfigError("'rows' must be a non-negative integer.")


def _validate_format(template: Any) -> None:
    if not isinstance(template, str) or not template:
        raise ConfigError("'format' must be a non-empty string.")


def _validate_types(types: Any) -> None:
    if not isinstance(types, Mapping) or not types:
        raise ConfigError("'types' must be a non-empty object.")
    for name, spec in types.items():
        _validate_type_spec(name, spec)


def _validate_type_spec(name: str, spec: Any) -> None:
    # Unknown-key diagnostics belong to the compiler, which knows which keys
    # each generator declares: guessing here rejected plugin-owned keys that
    # merely resemble a common one, before ownership was resolved (CFG-005).
    validated = _require_type_spec(name, spec)
    _validate_transform_specs(name, validated.get("transforms", []))
    _validate_validator_refs(name, validated.get("validators", []))


def _require_type_spec(name: str, spec: Any) -> Mapping[str, Any]:
    if not isinstance(spec, Mapping) or "type" not in spec:
        raise ConfigError(f"Type spec {name!r} must be an object with a 'type' field.")
    if not isinstance(spec["type"], str) or not spec["type"]:
        raise ConfigError(f"Type spec {name!r} 'type' must be a non-empty string.")
    return cast(Mapping[str, Any], spec)


def _validate_transform_specs(name: str, transforms: Any) -> None:
    if not isinstance(transforms, list):
        raise ConfigError(f"Type spec {name!r} 'transforms' must be a list.")
    for index, transform in enumerate(transforms):
        if not isinstance(transform, Mapping) or "type" not in transform:
            raise ConfigError(
                f"Type spec {name!r} transform {index} must be an object with a 'type' field."
            )
        if not isinstance(transform["type"], str) or not transform["type"]:
            raise ConfigError(
                f"Type spec {name!r} transform {index} 'type' must be a non-empty string."
            )


def _validate_validator_refs(name: str, validators: Any) -> None:
    if not isinstance(validators, list):
        raise ConfigError(f"Type spec {name!r} 'validators' must be a list.")
    if any(not isinstance(reference, str) for reference in validators):
        raise ConfigError(f"Type spec {name!r} validator refs must be strings.")


def _validate_template_references(template: str, types: Mapping[str, Any]) -> None:
    """Delegate to :func:`ton.template.validate_against` (DEC-002)."""
    try:
        validate_against(template, types.keys())
    except UndeclaredVariableError as exc:
        raise ConfigError(str(exc)) from exc

"""Config file loading and structural validation.

Per-type validation (e.g. ``minValue <= maxValue``, ``decimals >= 0``,
``values`` non-empty) lives in each :class:`ton.generators.Generator`'s
``prepare`` method and runs when the :class:`ton.engine.Engine` is
constructed. This module is intentionally type-agnostic so the two
validation surfaces cannot drift (TODO REL-011).
"""

from __future__ import annotations

import codecs
import difflib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from ._logging import LogEvent
from ._logging import logger as _logger
from ._registry import ExtensionCatalog, RegistryError, normalize_reference
from ._template import UndeclaredVariableError, validate_against
from ._transforms import fold_paired_capabilities
from .generators.base import PreparationContext


class ConfigError(ValueError):
    """Raised when a config file is missing required keys or has wrong types."""


_REQUIRED_TOP_LEVEL = ("rows", "format", "types")
ROOT_KEYS = frozenset((*_REQUIRED_TOP_LEVEL, "encoding"))
COMMON_FIELD_KEYS = frozenset(("type", "transforms", "validators"))


def _unknown_key_message(path: str, key: str, allowed: frozenset[str]) -> str:
    """Return a stable unknown-key diagnostic with a typo suggestion."""
    matches = difflib.get_close_matches(key, allowed, n=1, cutoff=0.6)
    suggestion = f" Did you mean {matches[0]!r}?" if matches else ""
    return f"Unknown key {path}.{key}.{suggestion} Allowed keys: {', '.join(sorted(allowed))}."


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


def validate_with_catalog(data: dict[str, Any], catalog: ExtensionCatalog) -> None:
    """Validate type and transform references against ``catalog``.

    Also runs each field's ``Generator.prepare`` so per-spec errors
    (bounds, value lists, output caps) surface here rather than only at
    generation time -- otherwise ``--validate`` reports a bad-bounds
    config as valid and the real run fails (CLI-001).
    """
    _validate(data)
    generators = catalog.generators()
    for field_name, spec in data["types"].items():
        _validate_type_reference(field_name, spec["type"], catalog)
        _validate_transforms(field_name, spec, catalog)
        _validate_field_validators(field_name, spec, catalog)
        _validate_field_spec(field_name, spec, generators)
    _logger.info(
        "config_validated types=%d",
        len(data["types"]),
        extra={
            "event": LogEvent.CONFIG_VALIDATED.value,
            "types": len(data["types"]),
            "available_types": catalog.list_data_types(),
            "available_transforms": catalog.list_transforms(),
        },
    )


def _validate(data: Any) -> None:
    _validate_root(data)
    _validate_rows(data["rows"])
    _validate_format(data["format"])
    _validate_types(data["types"])
    _validate_template_references(data["format"], data["types"])
    _validate_encoding(data)


def _validate_encoding(data: dict[str, Any]) -> None:
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
    if not isinstance(data, dict):
        raise ConfigError("Config root must be a JSON object.")
    missing = [key for key in _REQUIRED_TOP_LEVEL if key not in data]
    if missing:
        raise ConfigError(f"Config missing required keys: {missing}")
    unknown = set(data) - ROOT_KEYS
    if unknown:
        key = sorted(unknown)[0]
        raise ConfigError(_unknown_key_message("config", key, ROOT_KEYS))


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
    for key in spec:
        if key in COMMON_FIELD_KEYS:
            continue
        matches = difflib.get_close_matches(key, COMMON_FIELD_KEYS, n=1, cutoff=0.8)
        if matches:
            raise ConfigError(_unknown_key_message(f"types.{name}", key, COMMON_FIELD_KEYS))
    transforms = spec.get("transforms", [])
    if not isinstance(transforms, list):
        raise ConfigError(f"Type spec {name!r} 'transforms' must be a list.")
    for index, transform in enumerate(transforms):
        if not isinstance(transform, dict) or "type" not in transform:
            raise ConfigError(
                f"Type spec {name!r} transform {index} must be an object with a 'type' field."
            )
        if not isinstance(transform["type"], str) or not transform["type"]:
            raise ConfigError(
                f"Type spec {name!r} transform {index} 'type' must be a non-empty string."
            )


def _validate_template_references(template: str, types: dict[str, Any]) -> None:
    """Delegate to :func:`ton.template.validate_against` (TODO DEC-002)."""
    try:
        validate_against(template, types.keys())
    except UndeclaredVariableError as exc:
        raise ConfigError(str(exc)) from exc


def _validate_type_reference(
    field_name: str,
    reference: str,
    catalog: ExtensionCatalog,
) -> None:
    normalized = _normalize_config_reference(reference)
    if normalized not in catalog.generators():
        _raise_unknown_reference("type", field_name, reference, catalog.list_data_types())


def _validate_transforms(
    field_name: str,
    spec: dict[str, Any],
    catalog: ExtensionCatalog,
) -> None:
    generator = catalog.generators()[_normalize_config_reference(spec["type"])]
    is_paired = bool(generator.is_paired)
    for transform_spec in spec.get("transforms", []):
        reference = transform_spec["type"]
        normalized = _normalize_config_reference(reference)
        transforms = catalog.transforms()
        if normalized not in transforms:
            _raise_unknown_reference("transform", field_name, reference, catalog.list_transforms())
        transform = transforms[normalized]
        _validate_extension_keys(
            f"types.{field_name}.transforms",
            transform_spec,
            transform.config_keys,
            frozenset(("type",)),
        )
        capability = fold_paired_capabilities(is_paired, (transform.capabilities,))
        if capability.incompatible_index is not None:
            raise ConfigError(
                f"Transform {reference!r} for {field_name!r} does not accept paired input."
            )
        is_paired = capability.preserves_pairing


def _validate_field_validators(
    field_name: str,
    spec: dict[str, Any],
    catalog: ExtensionCatalog,
) -> None:
    """Validate a field's ``validators`` references against ``catalog`` (PLUG-001)."""
    references = spec.get("validators", [])
    if not isinstance(references, list):
        raise ConfigError(f"Type spec {field_name!r} 'validators' must be a list.")
    available = catalog.validators()
    for reference in references:
        if not isinstance(reference, str):
            raise ConfigError(f"Type spec {field_name!r} validator refs must be strings.")
        if _normalize_config_reference(reference) not in available:
            _raise_unknown_reference("validator", field_name, reference, catalog.list_validators())


def _validate_field_spec(
    field_name: str,
    spec: dict[str, Any],
    generators: Mapping[str, Any],
) -> None:
    """Run the generator's prepare so per-spec errors surface (CLI-001)."""
    generator = generators[_normalize_config_reference(spec["type"])]
    _validate_extension_keys(f"types.{field_name}", spec, generator.config_keys, COMMON_FIELD_KEYS)
    try:
        PreparationContext(generators).prepare_generator(generator, spec)
    except Exception as exc:  # noqa: BLE001 - boundary; normalized to ConfigError
        raise ConfigError(f"Invalid spec for {field_name!r}: {exc}") from exc


def _validate_extension_keys(
    path: str,
    spec: Mapping[str, Any],
    extension_keys: frozenset[str] | None,
    common_keys: frozenset[str],
) -> None:
    if extension_keys is None:
        return
    allowed = common_keys | extension_keys
    unknown = set(spec) - allowed
    if unknown:
        key = sorted(unknown)[0]
        raise ConfigError(_unknown_key_message(path, key, allowed))


def _normalize_config_reference(reference: str) -> str:
    try:
        return normalize_reference(reference)
    except RegistryError as exc:
        raise ConfigError(str(exc)) from exc


def _raise_unknown_reference(
    kind: str,
    field_name: str,
    reference: str,
    available: tuple[str, ...],
) -> None:
    namespace = _unknown_namespace(reference, available)
    detail = f" Unknown namespace {namespace!r}." if namespace else ""
    raise ConfigError(
        f"Unknown {kind} {reference!r} for {field_name!r}.{detail} "
        f"Available {kind}s: {', '.join(available) or '(none)'}."
    )


def _unknown_namespace(reference: str, available: tuple[str, ...]) -> str | None:
    if "." not in reference:
        return None
    namespace = reference.split(".", 1)[0]
    known = {item.split(".", 1)[0] for item in available if "." in item}
    return namespace if namespace not in known else None

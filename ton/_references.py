"""Namespaced reference syntax and resolution without catalog dependencies."""

from __future__ import annotations

import re
from collections.abc import Mapping

CORE_NAMESPACE = "core"
_ASCII_IDENTIFIER = re.compile(r"[A-Za-z0-9_]+\Z")


class RegistryError(ValueError):
    """Raised when plugin registration would make lookup ambiguous."""


def normalize_reference(reference: str) -> str:
    """Return a qualified registry reference."""
    _validate_reference(reference)
    if "." in reference:
        return reference
    return f"{CORE_NAMESPACE}.{reference}"


def resolve_reference[T](registry: Mapping[str, T], reference: str) -> T | None:
    """Resolve qualified or bare references using registry namespace rules."""
    normalized = normalize_reference(reference)
    for key in (normalized, reference, normalized.removeprefix(f"{CORE_NAMESPACE}.")):
        value = registry.get(key)
        if value is not None:
            return value
    return None


def runtime_type_name(reference: object) -> str:
    """Return the bare runtime key for a built-in qualified reference."""
    if isinstance(reference, str):
        return normalize_reference(reference).removeprefix(f"{CORE_NAMESPACE}.")
    return str(reference)


def _validate_reference(reference: str) -> None:
    parts = reference.split(".")
    if len(parts) == 1:
        _validate_identifier("name", parts[0])
        return
    if len(parts) == 2:
        _validate_identifier("namespace", parts[0])
        _validate_identifier("name", parts[1])
        return
    raise RegistryError(f"invalid registry reference {reference!r}")


def _validate_identifier(label: str, value: str) -> None:
    if _ASCII_IDENTIFIER.fullmatch(value) is None:
        raise RegistryError(f"{label} must contain only ASCII letters, numbers, or '_'")

"""Shared extension-owned config-key diagnostics."""

from __future__ import annotations

import difflib
from collections.abc import Callable, Mapping
from typing import Any

COMMON_FIELD_KEYS = frozenset(("type", "transforms", "validators"))
type PathLabel = str | Callable[[], str]


def unknown_key_message(path: str, key: str, allowed: frozenset[str]) -> str:
    """Return a stable unknown-key diagnostic with a typo suggestion."""
    matches = difflib.get_close_matches(key, allowed, n=1, cutoff=0.6)
    suggestion = f" Did you mean {matches[0]!r}?" if matches else ""
    return f"Unknown key {path}.{key}.{suggestion} Allowed keys: {', '.join(sorted(allowed))}."


def extension_key_error(
    path: PathLabel,
    spec: Mapping[str, Any],
    extension_keys: frozenset[str] | None,
    common_keys: frozenset[str],
) -> str | None:
    """Return the first extension-owned unknown-key error, if any."""
    if extension_keys is None:
        return None
    allowed = common_keys | extension_keys
    unknown = set(spec) - allowed
    if not unknown:
        return None
    key = min(unknown)
    return unknown_key_message(path() if callable(path) else path, key, allowed)


def require_known_keys(
    path: PathLabel,
    spec: Mapping[str, Any],
    allowed: frozenset[str],
) -> None:
    """Reject the first unknown key in an extension-owned nested object."""
    error = extension_key_error(path, spec, allowed, frozenset())
    if error is not None:
        raise ValueError(error)

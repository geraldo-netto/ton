"""Shared extension-owned config-key diagnostics."""

from __future__ import annotations

import difflib
from collections.abc import Mapping
from typing import Any

COMMON_FIELD_KEYS = frozenset(("type", "transforms", "validators"))


def unknown_key_message(path: str, key: str, allowed: frozenset[str]) -> str:
    """Return a stable unknown-key diagnostic with a typo suggestion."""
    matches = difflib.get_close_matches(key, allowed, n=1, cutoff=0.6)
    suggestion = f" Did you mean {matches[0]!r}?" if matches else ""
    return f"Unknown key {path}.{key}.{suggestion} Allowed keys: {', '.join(sorted(allowed))}."


def extension_key_error(
    path: str,
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
    key = sorted(unknown)[0]
    return unknown_key_message(path, key, allowed)

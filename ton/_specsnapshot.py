"""Isolated snapshots of caller-provided config specs.

``CompiledPlan`` describes immutable configuration artifacts and proof audit
records quote the spec a value was generated from, but both used to retain
the caller's own nested mappings. Mutating a values list after the first row
therefore changed an already-recorded failure, while the audit writer reused
its identity-cached fingerprint and reported a spec that no longer existed
(ARCH-006).

Snapshots are plain dicts and lists rather than read-only views: prepared
engines are pickled across process boundaries and audit records are
serialized to JSON, neither of which supports ``MappingProxyType``. Copying
also normalizes read-only inputs a caller may pass in.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def snapshot_spec(value: Any) -> Any:
    """Return a deep, independently owned copy of ``value``."""
    if isinstance(value, Mapping):
        return {key: snapshot_spec(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [snapshot_spec(item) for item in value]
    return value

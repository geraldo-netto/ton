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
    """Return a deep, independently owned copy of ``value``.

    Copying iteratively keeps engine construction stack-safe for deeply
    nested composite specs: this runs before the compiler can size its
    recursion head-room, so it must not recurse itself (SCALE-007).
    """
    root: list[Any] = [None]
    # Preserve aliases and cycles within the isolated graph (SCALE-012).
    memo: dict[int, Any] = {}
    pending: list[tuple[Any, Any, Any]] = [(root, 0, value)]
    while pending:
        target, key, item = pending.pop()
        if id(item) in memo:
            target[key] = memo[id(item)]
        elif isinstance(item, Mapping):
            copied: Any = {}
            memo[id(item)] = copied
            target[key] = copied
            pending.extend((copied, item_key, sub) for item_key, sub in item.items())
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            copied = [None] * len(item)
            memo[id(item)] = copied
            target[key] = copied
            pending.extend((copied, index, sub) for index, sub in enumerate(item))
        else:
            target[key] = item
    return root[0]

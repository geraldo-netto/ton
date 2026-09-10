"""Isolated snapshots of caller-provided config specs.

``CompiledPlan`` describes immutable configuration artifacts and proof audit
records quote the spec a value was generated from, but both used to retain
the caller's own nested mappings. Mutating a values list after the first row
therefore changed an already-recorded failure, while the audit writer reused
its identity-cached fingerprint and reported a spec that no longer existed
(ARCH-006).

Snapshots normalize mappings and sequences, preserving shared containers and
cycles. Audit snapshots expose read-only containers that support pickle and
TON's JSON encoder, preventing consumers from mutating retained content.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any


class FrozenMapping(Mapping[str, Any]):
    """Read-only mapping backed by an exclusively owned snapshot."""

    def __init__(self, values: dict[str, Any]) -> None:
        self._values = values

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


class FrozenSequence(Sequence[Any]):
    """Read-only sequence retaining list-like value equality for audit consumers."""

    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def __getitem__(self, index: Any) -> Any:
        return self._values[index]

    def __len__(self) -> int:
        return len(self._values)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Sequence) and list(self) == list(other)


def snapshot_spec(value: Any, *, immutable: bool = False) -> Any:
    """Return a deep, independently owned copy, optionally through read-only containers.

    Copying iteratively keeps engine construction stack-safe for deeply
    nested composite specs, independently of the caller's recursion limit
    and the compiler's preparation work stack (SCALE-007).
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
            view = FrozenMapping(copied) if immutable else copied
            memo[id(item)] = view
            target[key] = view
            pending.extend((copied, item_key, sub) for item_key, sub in item.items())
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            copied = [None] * len(item)
            view = FrozenSequence(copied) if immutable else copied
            memo[id(item)] = view
            target[key] = view
            pending.extend((copied, index, sub) for index, sub in enumerate(item))
        else:
            target[key] = item
    return root[0]

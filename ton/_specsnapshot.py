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

from collections.abc import Iterable, Iterator, Mapping, Sequence
from copy import deepcopy
from typing import Any, cast


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


def snapshot_fields(types: Mapping[str, Any], field_keys: Iterable[str]) -> dict[str, Any]:
    """Copy selected roots together, preserving their order and shared metadata."""
    selected = set(field_keys)
    return cast(
        dict[str, Any], snapshot_spec({key: spec for key, spec in types.items() if key in selected})
    )


def snapshot_spec(value: Any, *, immutable: bool = False) -> Any:
    """Return a deep, independently owned copy, optionally through read-only containers.

    Copying iteratively keeps engine construction stack-safe for deeply
    nested composite specs, independently of the caller's recursion limit
    and the compiler's preparation work stack (SCALE-007).
    """
    root: list[Any] = [None]
    # Preserve aliases and cycles within the isolated graph (SCALE-012).
    memo: dict[int, Any] = {}
    # Computed containers can release children as iteration advances. Keep
    # memoized sources alive so their IDs cannot alias later children (REL-057).
    sources: list[Any] = []
    opaque: list[tuple[Any, Any, Any]] = []
    # Keep one iterator per active container, not one queued task per entry.
    pending: list[tuple[Any, Iterator[tuple[Any, Any]]]] = [(root, iter(((0, value),)))]
    while pending:
        target, entries = pending[-1]
        try:
            key, item = next(entries)
        except StopIteration:
            pending.pop()
            continue
        if id(item) in memo:
            target[key] = memo[id(item)]
        elif isinstance(item, Mapping):
            sources.append(item)
            copied: Any = {}
            view = FrozenMapping(copied) if immutable else copied
            memo[id(item)] = view
            target[key] = view
            pending.append((copied, iter(item.items())))
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            sources.append(item)
            copied = [None] * len(item)
            view = FrozenSequence(copied) if immutable else copied
            memo[id(item)] = view
            target[key] = view
            pending.append((copied, enumerate(item)))
        elif type(item) in (str, bytes, int, float, bool, type(None)):
            target[key] = item
        else:
            opaque.append((target, key, item))
    _copy_opaque(opaque, memo)
    return root[0]


def _copy_opaque(entries: list[tuple[Any, Any, Any]], memo: dict[int, Any]) -> None:
    """Copy plugin state after normal containers have all acquired memo entries.

    Forward references from opaque objects then resolve to the same normalized
    containers, including read-only audit views, as direct references (REL-059).
    Custom objects retain their own deepcopy protocol and type.
    """
    for target, key, item in entries:
        try:
            target[key] = deepcopy(item, memo)
        except Exception as exc:
            raise ValueError(
                f"Cannot snapshot opaque config value of type {type(item).__name__}"
            ) from exc

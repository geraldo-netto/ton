"""Explicit mapping-key/list-index locations for owned generator specifications."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import cast

type SpecPath = tuple[str | int, ...]


@dataclass(frozen=True, eq=False, slots=True)
class SpecLocation:
    """Shared parent path with incremental hashing; flatten only for diagnostics.

    Equal extensions of a shared parent compare only their new components.
    This lets preparation resolve a child without copying or hashing its ancestors.
    """

    parent: SpecLocation | None = None
    part: str | int | None = None
    depth: int = field(init=False)
    _hash: int = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "depth", 0 if self.parent is None else self.parent.depth + 1)
        object.__setattr__(self, "_hash", hash((hash(self.parent), self.part)))

    def __add__(self, parts: SpecPath) -> SpecLocation:
        location = self
        for part in parts:
            location = SpecLocation(location, part)
        return location

    def __hash__(self) -> int:
        return self._hash

    def __eq__(self, other: object) -> bool:
        if (
            not isinstance(other, SpecLocation)
            or self.depth != other.depth
            or hash(self) != hash(other)
        ):
            return False
        left, right = self, other
        while left is not right and left.parent is not None:
            if left.part != right.part:
                return False
            left, right = left.parent, cast(SpecLocation, right.parent)
        return True

    def __iter__(self) -> Iterator[str | int]:
        parts: list[str | int] = []
        location = self
        while location.parent is not None:
            parts.append(cast(str | int, location.part))
            location = location.parent
        return iter(reversed(parts))

    def __bool__(self) -> bool:
        return bool(self.depth)

    def __str__(self) -> str:
        return format_spec_path(self)

    def __repr__(self) -> str:
        return repr(str(self))

    def __reduce__(self) -> tuple[object, tuple[SpecPath]]:
        # Flatten on serialization; rebuild hashes in the receiving interpreter.
        return _location_from_parts, (tuple(self),)


def _location_from_parts(parts: SpecPath) -> SpecLocation:
    return SpecLocation() + parts


def format_spec_path(path: Iterable[str | int]) -> str:
    """Render a location for diagnostics; never parse this text to traverse a spec."""
    return "".join(f"[{key}]" if isinstance(key, int) else f".{key}" for key in path).lstrip(".")

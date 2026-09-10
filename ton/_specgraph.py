"""Declared generator ownership shared by compilation and worker partitioning."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from ._contracts import Generator
from ._references import resolve_reference
from ._specpath import SpecPath
from ._transforms import Transform


@dataclass(frozen=True)
class OwnedChild:
    """One physical child occurrence and the extension that owns its location."""

    location: SpecPath
    spec: Mapping[str, Any]
    owner: Generator | Transform
    owner_spec: Mapping[str, Any]


@dataclass(frozen=True)
class FieldOwnership:
    uses_source: bool
    source_children: tuple[OwnedChild, ...]
    transform_children: tuple[OwnedChild, ...]


def resolve_generator(
    spec: Mapping[str, Any],
    registry: Mapping[str, Generator],
) -> Generator | None:
    reference = spec.get("type")
    return resolve_reference(registry, reference) if isinstance(reference, str) else None


def field_ownership(
    spec: Mapping[str, Any],
    generator: Generator | None,
    transforms: Mapping[str, Transform],
    *,
    include_inactive_source: bool = True,
) -> FieldOwnership:
    """Describe ownership without deciding whether inactive sources need preparation."""
    uses_source = True
    children: list[OwnedChild] = []
    for index, transform_spec, transform in _transform_owners(spec, transforms):
        if index == 0:
            uses_source = transform.requires_source
        children.extend(_owned_children(transform, transform_spec, ("transforms", index)))
    source = (
        _owned_children(generator, spec, ())
        if generator is not None and (uses_source or include_inactive_source)
        else ()
    )
    return FieldOwnership(uses_source, source, tuple(children))


def _owned_children(
    owner: Generator | Transform,
    spec: Mapping[str, Any],
    prefix: SpecPath,
) -> tuple[OwnedChild, ...]:
    return tuple(
        OwnedChild(prefix + location, child, owner, spec)
        for location, child in owner.nested_specs(spec)
    )


def _transform_owners(
    spec: Mapping[str, Any],
    registry: Mapping[str, Transform],
) -> Iterator[tuple[int, Mapping[str, Any], Transform]]:
    raw = spec.get("transforms", [])
    if not isinstance(raw, list):
        return
    for index, transform_spec in enumerate(raw):
        if not isinstance(transform_spec, Mapping):
            continue
        reference = transform_spec.get("type")
        if not isinstance(reference, str):
            continue
        transform = resolve_reference(registry, reference)
        if transform is not None:
            yield index, transform_spec, transform

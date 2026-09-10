"""Optional extension capability for worker-local settings and child draw offsets."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ._specpath import SpecPath


@dataclass(frozen=True)
class PartitionSpec:
    """Settings to update and absolute preceding draw-slot counts for owned children.

    Child locations are relative to this extension's spec, as in nested_specs.
    Unspecified children inherit the incoming offset. Updates change the owner's
    settings, never the type, pipeline stages, or declared child containers.
    """

    updates: Mapping[str, Any] = field(default_factory=dict)
    child_offsets: Mapping[SpecPath, int] = field(default_factory=dict)


@runtime_checkable
class Partitionable(Protocol):
    """Opt in to partitioning; offset counts previously reserved draw slots."""

    def partition(self, spec: Mapping[str, Any], offset: int) -> PartitionSpec: ...

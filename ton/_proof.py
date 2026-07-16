"""Proof-check primitives for generated rows."""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import cached_property
from typing import Any

from ._transforms import TransformResult

#: Placeholder substituted for sensitive proof-failure fields (DG-002).
REDACTED = "<redacted>"


@dataclass(frozen=True)
class PreparedTransform:
    """A transform paired with its immutable prepared configuration."""

    transform: Any
    prepared: Any


@dataclass(frozen=True)
class PreparedField:
    """Prepared source and proof trace metadata for one template field."""

    generator: Any
    source_prepared: Any
    transforms: tuple[PreparedTransform, ...]
    validators: tuple[Any, ...] = ()

    @cached_property
    def is_paired(self) -> bool:
        if not self.transforms:
            return bool(self.generator.is_paired)
        last = self.transforms[-1].transform
        return bool(self.generator.is_paired and last.capabilities.preserves_pairing)

    @cached_property
    def is_direct(self) -> bool:
        """Whether proof-off generation needs only the source generator call."""
        return not self.is_paired and not self.transforms and not self.validators


@dataclass(frozen=True)
class TransformStep:
    """Before/after trace for one prepared transform application."""

    prepared: PreparedTransform
    before: TransformResult
    after: TransformResult


@dataclass(frozen=True)
class ProofResult:
    """Result returned by a generator or transform proof hook."""

    ok: bool
    reason: str = ""


@dataclass(frozen=True)
class ProofFailure:
    """Context needed to diagnose a failed proof check."""

    row: int
    type_key: str
    stage: str
    reference: str
    reason: str
    value: str
    id_value: str | None = None
    seed: int | None = None
    spec: dict[str, Any] | None = None

    def redacted(self) -> ProofFailure:
        """Return a copy with the sensitive fields masked (DG-002).

        The generated ``value`` / ``id_value`` and the full field ``spec``
        can carry synthetic identifiers or source value pools, so records
        destined for manifests or audit exports should be redacted first.
        The diagnostic fields (row, type_key, stage, reference, reason)
        are preserved.
        """
        return replace(
            self,
            value=REDACTED,
            id_value=REDACTED if self.id_value is not None else None,
            spec=None,
        )


@dataclass(frozen=True)
class ProvenanceRecord:
    """Metadata describing how one template field is generated."""

    type_key: str
    source_type: str
    transforms: tuple[str, ...]
    proof_mode: str
    proof_sample_rate: int
    proof_failures: int = 0
    plugin_package: str | None = None
    plugin_version: str | None = None

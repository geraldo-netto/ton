"""Proof-check primitives for generated rows."""

from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, replace
from functools import cached_property
from typing import Any

from ._transforms import TransformResult

#: Placeholder substituted for sensitive proof-failure fields (DG-002).
REDACTED = "<redacted>"

# Scoped to one Engine row, including nested generator calls.
# Standalone child draws retain traces so callers can prove them afterward.
_trace_enabled: ContextVar[bool] = ContextVar("ton_proof_trace_enabled", default=True)


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
    is_paired: bool = False
    source_is_paired: bool = False
    uses_source: bool = True
    validators: tuple[Any, ...] = ()
    provider: tuple[str | None, str | None] = (None, None)

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
    spec: Mapping[str, Any] | None = None
    is_redacted: bool = False

    def redacted(self) -> ProofFailure:
        """Return a copy with the sensitive fields masked (DG-002).

        The generated ``value`` / ``id_value``, full field ``spec``, and
        plugin-controlled ``reason`` can carry synthetic identifiers or
        source value pools, so records destined for logs or audit exports
        should be redacted first. Structural diagnostic fields remain visible.
        """
        redacted: ProofFailure = replace(
            self,
            reason=REDACTED,
            value=REDACTED,
            id_value=REDACTED if self.id_value is not None else None,
            spec=None,
            is_redacted=True,
        )
        return redacted


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


def proof_result(ok: bool, reason: str) -> ProofResult:
    """Build a compact proof result with a reason only on failure."""
    return ProofResult(ok=ok, reason="" if ok else reason)

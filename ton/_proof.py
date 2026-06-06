"""Proof-check primitives for generated rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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

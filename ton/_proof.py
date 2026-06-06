"""Proof-check primitives for generated rows."""

from __future__ import annotations

from dataclasses import dataclass


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

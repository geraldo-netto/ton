"""Streaming proof-audit report serialization.

Proof reports use UTF-8 JSON Lines: each line is one complete
``ton.proof-audit/v2`` failure record, so consumers can process arbitrarily
large reports without loading them in memory. The CLI exposes the destination
as ``--proof-report PATH``.

Clear records include generated ``value``, paired ``id_value`` when present,
and the field ``spec``. With redaction enabled those fields follow
:meth:`ProofFailure.redacted`: values and free-form reasons become
``"<redacted>"`` and the spec becomes ``null``. Structural diagnostic and
provenance fields remain visible.
"""

from __future__ import annotations

import hashlib
from typing import TextIO

from ._json import iter_json
from ._proof import ProofFailure

PROOF_AUDIT_SCHEMA = "ton.proof-audit/v2"


class ProofAuditWriteError(OSError):
    """A proof-audit record could not be written to its report stream."""


class ProofAuditWriter:
    """Serialize proof failures to a JSON Lines text stream.

    Redaction belongs to the proof layer. The writer records the state carried
    by each failure so its schema marker cannot disagree with its payload.
    """

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self._emitted_specs: set[str] = set()
        self._spec_references: dict[str, tuple[object, str]] = {}

    def __call__(self, failure: ProofFailure) -> None:
        spec_ref = self._reference_for(failure.type_key, failure.spec)
        emit_spec = spec_ref is not None and spec_ref not in self._emitted_specs
        payload = {
            "schema": PROOF_AUDIT_SCHEMA,
            "redacted": failure.is_redacted,
            "row": failure.row,
            "type_key": failure.type_key,
            "stage": failure.stage,
            "reference": failure.reference,
            "reason": failure.reason,
            "value": failure.value,
            "id_value": failure.id_value,
            "seed": failure.seed,
            "spec_ref": spec_ref,
            "spec": failure.spec if emit_spec else None,
        }
        try:
            self._stream.write("".join(iter_json(payload)) + "\n")
        except OSError as exc:
            raise ProofAuditWriteError(str(exc)) from exc
        if spec_ref is not None:
            self._emitted_specs.add(spec_ref)

    def _reference_for(self, type_key: str, spec: object | None) -> str | None:
        if spec is None:
            return None
        cached = self._spec_references.get(type_key)
        if cached is not None and cached[0] is spec:
            return cached[1]
        reference = _spec_reference(spec)
        self._spec_references[type_key] = (spec, reference)
        return reference


def _spec_reference(spec: object) -> str:
    digest = hashlib.sha256()
    for token in iter_json(spec, sort_keys=True):
        digest.update(token.encode("utf-8"))
    return f"sha256:{digest.hexdigest()}"

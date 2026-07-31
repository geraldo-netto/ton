"""Streaming proof-audit report serialization.

Proof reports use UTF-8 JSON Lines: each line is one complete
``ton.proof-audit/v1`` failure record, so consumers can process arbitrarily
large reports without loading them in memory. The CLI exposes the destination
as ``--proof-report PATH``.

Clear records include generated ``value``, paired ``id_value`` when present,
and the field ``spec``. With redaction enabled those fields follow
:meth:`ProofFailure.redacted`: values become ``"<redacted>"`` and the spec
becomes ``null``. Diagnostic and provenance fields remain visible.
"""

from __future__ import annotations

import json
from typing import TextIO

from ._proof import ProofFailure

PROOF_AUDIT_SCHEMA = "ton.proof-audit/v1"


class ProofAuditWriteError(OSError):
    """A proof-audit record could not be written to its report stream."""


class ProofAuditWriter:
    """Serialize proof failures to a JSON Lines text stream.

    Redaction belongs to the proof layer. The writer records the state carried
    by each failure so its schema marker cannot disagree with its payload.
    """

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def __call__(self, failure: ProofFailure) -> None:
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
            "spec": failure.spec,
        }
        try:
            self._stream.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
        except OSError as exc:
            raise ProofAuditWriteError(str(exc)) from exc

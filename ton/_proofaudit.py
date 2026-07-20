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
    """Serialize proof failures to a JSON Lines text stream."""

    def __init__(self, stream: TextIO, *, redact: bool = False) -> None:
        self._stream = stream
        self._redact = redact

    def __call__(self, failure: ProofFailure) -> None:
        visible = failure.redacted() if self._redact else failure
        payload = {
            "schema": PROOF_AUDIT_SCHEMA,
            "redacted": self._redact,
            "row": visible.row,
            "type_key": visible.type_key,
            "stage": visible.stage,
            "reference": visible.reference,
            "reason": visible.reason,
            "value": visible.value,
            "id_value": visible.id_value,
            "seed": visible.seed,
            "spec": visible.spec,
        }
        try:
            self._stream.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
        except OSError as exc:
            raise ProofAuditWriteError(f"cannot write proof-audit report: {exc}") from exc

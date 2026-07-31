"""Proof-audit report schema and streaming behavior."""

from __future__ import annotations

import io
import json
from random import Random
from typing import Any

import pytest

from ton import _proofcheck as proofcheck
from ton._proof import REDACTED, PreparedField, ProofFailure, ProofResult
from ton._proofaudit import PROOF_AUDIT_SCHEMA, ProofAuditWriteError, ProofAuditWriter
from ton._proofcheck import ProofChecker
from ton._transforms import TransformResult
from ton.generators import Generator


def _failure() -> ProofFailure:
    return ProofFailure(
        row=7,
        type_key="credential",
        stage="source",
        reference="paired",
        reason="mismatch",
        value="secret",
        id_value="secret-id",
        seed=42,
        spec={"type": "paired", "values": ["secret"]},
    )


def test_proof_audit_writer_emits_clear_json_line() -> None:
    stream = io.StringIO()

    ProofAuditWriter(stream)(_failure())

    record = json.loads(stream.getvalue())
    assert record == {
        "schema": PROOF_AUDIT_SCHEMA,
        "redacted": False,
        "row": 7,
        "type_key": "credential",
        "stage": "source",
        "reference": "paired",
        "reason": "mismatch",
        "value": "secret",
        "id_value": "secret-id",
        "seed": 42,
        "spec": {"type": "paired", "values": ["secret"]},
    }
    assert stream.getvalue().endswith("\n")


def test_proof_audit_writer_uses_failure_redaction_state() -> None:
    stream = io.StringIO()

    ProofAuditWriter(stream)(_failure().redacted())

    record = json.loads(stream.getvalue())
    assert record["redacted"] is True
    assert record["value"] == REDACTED
    assert record["id_value"] == REDACTED
    assert record["spec"] is None
    assert record["reason"] == "mismatch"


@pytest.mark.parametrize("redact", [False, True])
def test_proof_checker_owns_sink_redaction(redact: bool) -> None:
    stream = io.StringIO()
    checker = ProofChecker(
        mode="audit",
        sample_rate=1,
        seed=42,
        redact=redact,
        failure_sink=ProofAuditWriter(stream),
    )

    checker._record_audit(_failure())

    record = json.loads(stream.getvalue())
    assert record["redacted"] is redact
    assert record["value"] == checker.failures[0].value
    assert record["spec"] == checker.failures[0].spec


def test_proof_audit_writer_maps_stream_errors() -> None:
    class BrokenStream(io.StringIO):
        def write(self, value: str) -> int:
            del value
            raise OSError("disk full")

    with pytest.raises(ProofAuditWriteError, match="disk full"):
        ProofAuditWriter(BrokenStream())(_failure())


def test_proof_checker_streams_details_beyond_retention_sample(monkeypatch) -> None:
    class FailingGenerator(Generator):
        type_name = "failing"

        def generate(self, prepared: Any, rng: Random) -> str:
            del prepared, rng
            return "bad"

        def prove(self, prepared: Any, result: TransformResult) -> ProofResult:
            del prepared, result
            return ProofResult(ok=False, reason="bad value")

    monkeypatch.setattr(proofcheck, "MAX_AUDIT_SAMPLE", 2)
    stream = io.StringIO()
    checker = ProofChecker(
        mode="audit",
        sample_rate=1,
        seed=9,
        failure_sink=ProofAuditWriter(stream),
    )
    field = PreparedField(
        generator=FailingGenerator(),
        source_prepared={},
        transforms=(),
    )

    for row in range(5):
        assert (
            checker.evaluate(
                "v",
                field,
                TransformResult("bad"),
                (),
                rows_emitted=row,
                spec={"type": "failing"},
            )
            is None
        )

    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert checker.failure_count == 5
    assert len(checker.failures) == 2
    assert [record["row"] for record in records] == [1, 2, 3, 4, 5]
    assert all(record["spec"] == {"type": "failing"} for record in records)

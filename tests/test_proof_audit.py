"""Proof-audit report schema and streaming behavior."""

from __future__ import annotations

import io
import json
import logging
from random import Random
from typing import Any

import pytest

from ton import _proofaudit as proofaudit
from ton import _proofcheck as proofcheck
from ton._engine import Engine, ProofError
from ton._proof import REDACTED, PreparedField, ProofFailure, ProofResult
from ton._proofaudit import PROOF_AUDIT_SCHEMA, ProofAuditWriteError, ProofAuditWriter
from ton._proofcheck import ProofChecker, ProofFailureSinkError
from ton._transforms import TransformResult
from ton.generators import Generator


class _EchoingReasonGenerator(Generator):
    type_name = "echoing_reason"

    def generate(self, prepared: Any, rng: Random) -> str:
        del prepared, rng
        return "credential-secret"

    def prove(self, prepared: Any, result: TransformResult) -> ProofResult:
        del prepared
        return ProofResult(ok=False, reason=f"rejected {result.value}")


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
        "spec_ref": record["spec_ref"],
        "spec": {"type": "paired", "values": ["secret"]},
    }
    assert record["spec_ref"].startswith("sha256:")
    assert stream.getvalue().endswith("\n")


def test_proof_audit_writer_uses_failure_redaction_state() -> None:
    stream = io.StringIO()

    ProofAuditWriter(stream)(_failure().redacted())

    record = json.loads(stream.getvalue())
    assert record["redacted"] is True
    assert record["value"] == REDACTED
    assert record["id_value"] == REDACTED
    assert record["spec"] is None
    assert record["spec_ref"] is None
    assert record["reason"] == REDACTED


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
    assert record["reason"] == (REDACTED if redact else "mismatch")


def test_redaction_masks_echoing_reason_in_audit_report_and_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stream = io.StringIO()
    engine = Engine.from_config(
        {
            "rows": 1,
            "format": "$credential$",
            "types": {"credential": {"type": "echoing_reason"}},
        },
        registry={"echoing_reason": _EchoingReasonGenerator()},
        proof_mode="audit",
        redact_proof_failures=True,
        proof_failure_sink=ProofAuditWriter(stream),
    )

    with caplog.at_level(logging.WARNING, logger="ton"):
        assert list(engine) == ["credential-secret"]

    record = json.loads(stream.getvalue())
    failure_log = next(
        item for item in caplog.records if getattr(item, "event", "") == "proof_check_failed"
    )
    assert record["reason"] == REDACTED
    assert engine.proof_failures[0].reason == REDACTED
    assert failure_log.reason == REDACTED
    assert "credential-secret" not in stream.getvalue()


def test_strict_proof_redaction_masks_echoing_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = Engine.from_config(
        {
            "rows": 1,
            "format": "$credential$",
            "types": {"credential": {"type": "echoing_reason"}},
        },
        registry={"echoing_reason": _EchoingReasonGenerator()},
        proof_mode="all",
        redact_proof_failures=True,
    )

    def generate_with_logging() -> None:
        with caplog.at_level(logging.WARNING, logger="ton"):
            next(iter(engine))

    with pytest.raises(ProofError) as raised:
        generate_with_logging()

    failure_log = next(
        item for item in caplog.records if getattr(item, "event", "") == "proof_check_failed"
    )
    assert "credential-secret" not in str(raised.value)
    assert failure_log.reason == REDACTED


def test_proof_audit_writer_maps_stream_errors() -> None:
    class BrokenStream(io.StringIO):
        def write(self, value: str) -> int:
            del value
            raise OSError("disk full")

    writer = ProofAuditWriter(BrokenStream())
    failure = _failure()
    with pytest.raises(ProofAuditWriteError, match="disk full"):
        writer(failure)


def test_proof_audit_writer_emits_repeated_spec_once_by_stable_reference() -> None:
    stream = io.StringIO()
    writer = ProofAuditWriter(stream)

    writer(_failure())
    writer(_failure())

    first, second = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert first["spec"] == _failure().spec
    assert second["spec"] is None
    assert first["spec_ref"] == second["spec_ref"]


def test_proof_audit_writer_caches_repeated_spec_fingerprint(monkeypatch) -> None:
    calls = 0
    real_reference = proofaudit._spec_reference

    def counting_reference(spec: object) -> str:
        nonlocal calls
        calls += 1
        return real_reference(spec)

    monkeypatch.setattr(proofaudit, "_spec_reference", counting_reference)
    stream = io.StringIO()
    writer = ProofAuditWriter(stream)
    failure = _failure()

    writer(failure)
    writer(failure)

    assert calls == 1


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

    spec = {"type": "failing"}
    for row in range(5):
        assert (
            checker.evaluate(
                "v",
                field,
                TransformResult("bad"),
                (),
                rows_emitted=row,
                spec=spec,
            )
            is None
        )

    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert checker.failure_count == 5
    assert len(checker.failures) == 2
    assert [record["row"] for record in records] == [1, 2, 3, 4, 5]
    assert records[0]["spec"] == spec
    assert all(record["spec"] is None for record in records[1:])
    assert len({record["spec_ref"] for record in records}) == 1
    assert checker.failures[0].spec is checker.failures[1].spec


def test_engine_preserves_proof_sink_failure_boundary() -> None:
    class FailingGenerator(Generator):
        type_name = "failing"

        def generate(self, prepared: Any, rng: Random) -> str:
            del prepared, rng
            return "bad"

        def prove(self, prepared: Any, result: TransformResult) -> ProofResult:
            del prepared, result
            return ProofResult(ok=False, reason="bad value")

    def reject_failure(failure: ProofFailure) -> None:
        del failure
        raise RuntimeError("sink unavailable")

    engine = Engine.from_config(
        {"rows": 1, "format": "$v$", "types": {"v": {"type": "failing"}}},
        registry={"failing": FailingGenerator()},
        proof_mode="audit",
        proof_failure_sink=reject_failure,
    )

    with pytest.raises(ProofFailureSinkError, match="sink unavailable") as exc:
        list(engine)

    assert isinstance(exc.value.__cause__, RuntimeError)


@pytest.mark.parametrize("proof_mode", ["off", "sample", "all"])
def test_proof_failure_sink_requires_audit_mode(proof_mode: str) -> None:
    with pytest.raises(ValueError, match="requires proof_mode='audit'"):
        Engine.from_config(
            {
                "rows": 0,
                "format": "$value$",
                "types": {"value": {"type": "string", "values": ["valid"]}},
            },
            proof_mode=proof_mode,
            proof_failure_sink=lambda failure: None,
        )


def test_proof_failure_sink_must_be_callable() -> None:
    with pytest.raises(TypeError, match="must be callable"):
        Engine.from_config(
            {
                "rows": 0,
                "format": "$value$",
                "types": {"value": {"type": "string", "values": ["valid"]}},
            },
            proof_mode="audit",
            proof_failure_sink=object(),  # type: ignore[arg-type]
        )


def test_proof_failure_sink_cannot_change_after_iteration_starts() -> None:
    engine = Engine.from_config(
        {
            "rows": 1,
            "format": "$value$",
            "types": {"value": {"type": "string", "values": ["valid"]}},
        },
        proof_mode="audit",
    )
    iterator = iter(engine)

    with pytest.raises(RuntimeError, match="during iteration"):
        engine.set_proof_failure_sink(lambda failure: None)

    assert list(iterator) == ["valid"]
    with pytest.raises(RuntimeError, match="after iteration starts"):
        engine.set_proof_failure_sink(lambda failure: None)


def test_proof_checker_preserves_existing_sink_error() -> None:
    sink_error = ProofFailureSinkError("sink unavailable")

    def reject_failure(failure: ProofFailure) -> None:
        del failure
        raise sink_error

    checker = ProofChecker(
        mode="audit",
        sample_rate=1,
        seed=None,
        failure_sink=reject_failure,
    )
    failure = _failure()

    with pytest.raises(ProofFailureSinkError) as exc:
        checker._record_audit(failure)

    assert exc.value is sink_error

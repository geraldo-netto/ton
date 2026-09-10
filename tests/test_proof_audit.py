"""Proof-audit report schema and streaming behavior."""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Mapping
from decimal import Decimal
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


@pytest.mark.parametrize("number", ["0.10000000000000001", "-1.2300", "1e1000", "0.00000001"])
def test_audit_decimal_tokens_preserve_numeric_type_and_fingerprint(number) -> None:
    """CFG-007: both report payloads and fingerprints retain exact numeric syntax."""
    import hashlib
    from dataclasses import replace

    value = Decimal(number)
    stream = io.StringIO()
    ProofAuditWriter(stream)(replace(_failure(), spec={"value": value}))
    record = json.loads(stream.getvalue(), parse_float=Decimal)
    assert isinstance(record["spec"]["value"], (int, Decimal))
    assert record["spec"]["value"] == value
    canonical = '{"value":' + str(value) + "}"
    assert record["spec_ref"] == "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


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
    assert not hasattr(failure_log, "reason")
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
    assert not hasattr(failure_log, "reason")


def test_clear_proof_log_omits_plugin_controlled_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = Engine.from_config(
        {
            "rows": 1,
            "format": "$credential$",
            "types": {"credential": {"type": "echoing_reason"}},
        },
        registry={"echoing_reason": _EchoingReasonGenerator()},
        proof_mode="audit",
    )

    with caplog.at_level(logging.WARNING, logger="ton"):
        list(engine)

    failure_log = next(
        item for item in caplog.records if getattr(item, "event", "") == "proof_check_failed"
    )
    assert "reason" not in vars(failure_log)
    assert "credential-secret" not in repr(vars(failure_log))


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


def test_audit_serialization_still_rejects_unsupported_objects() -> None:
    """Decimal support must not silently serialize anything else (CFG-007)."""
    from ton._json import iter_json

    assert "".join(iter_json(Decimal("0.5"))) == "0.5"
    with pytest.raises(TypeError, match="not JSON serializable"):
        list(iter_json(object()))


def _rejecting_engine(values: list[str]):
    from ton._transforms import BaseTransform, TransformProof

    class _Reject(BaseTransform):
        type_name = "reject_arch"
        config_keys = frozenset()

        def prove(self, prepared, before, after):  # noqa: ANN001, ANN201
            del prepared, before, after
            return TransformProof(ok=False, reason="nope")

    config = {
        "rows": 3,
        "format": "$x$",
        "types": {
            "x": {"type": "string", "values": values, "transforms": [{"type": "reject_arch"}]}
        },
    }
    return Engine.from_config(
        config, seed=1, proof_mode="audit", transforms={"reject_arch": _Reject()}
    )


def test_caller_mutation_cannot_change_a_recorded_audit_spec() -> None:
    """The plan must not alias caller-owned config mappings (ARCH-006)."""
    values = ["a"]
    engine = _rejecting_engine(values)
    rows = iter(engine)

    next(rows)
    values.append("MUTATED")
    list(rows)

    specs = [failure.spec for failure in engine.proof_failures]
    assert specs
    assert all(spec["values"] == ["a"] for spec in specs)


def test_sink_mutation_cannot_reach_the_engine_snapshot() -> None:
    """A sink that mutates what it receives must not corrupt later records."""
    engine = _rejecting_engine(["a"])
    seen: list[Mapping[str, Any]] = []

    def _mutating_sink(failure: ProofFailure) -> None:
        if failure.spec is not None:
            seen.append(failure.spec)
            with pytest.raises(AttributeError):
                failure.spec["values"].append("FROM_SINK")

    engine.set_proof_failure_sink(_mutating_sink)
    list(engine)

    assert seen
    assert engine._plan.types["x"]["values"] == ["a"]


def test_exact_json_encoder_handles_containers_and_shared_values() -> None:
    """CFG-007: exact tokens retain ordinary JSON escaping and container semantics."""
    from ton._json import iter_json

    shared = {'quoted"\n': [True, False, None, 1.5, 3]}
    value = [shared, shared, (), {}, {2: "integer key"}]
    encoded = "".join(iter_json(value))
    assert json.loads(encoded) == json.loads(json.dumps(value))
    assert "".join(iter_json({"b": 1, "a": 2}, sort_keys=True)) == '{"a":2,"b":1}'
    value.append(value)
    with pytest.raises(ValueError, match="Circular reference"):
        list(iter_json(value))


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_exact_json_encoder_rejects_nonfinite_decimal(value) -> None:
    from ton._json import iter_json

    with pytest.raises(ValueError, match="Non-finite Decimal"):
        list(iter_json(value))


@pytest.mark.parametrize("sign", [-1, 1])
def test_audit_writes_arbitrary_integer_fields_and_seed(sign) -> None:
    """SCALE-013: reports and fingerprints preserve huge integers without global changes."""
    import hashlib
    import sys
    from dataclasses import replace

    from ton._scalars import str_to_int

    before = sys.get_int_max_str_digits()
    digits = ("-" if sign < 0 else "") + "1" + "0" * 4300
    bound = sign * 10**4300
    stream = io.StringIO()
    writer = ProofAuditWriter(stream)
    failure = replace(_failure(), seed=bound, row=bound, spec={"bound": bound})
    writer(failure)
    writer(failure)
    records = [json.loads(line, parse_int=str_to_int) for line in stream.getvalue().splitlines()]
    assert records[0]["spec"]["bound"] == records[0]["row"] == records[0]["seed"] == bound
    expected = "sha256:" + hashlib.sha256(('{"bound":' + digits + "}").encode()).hexdigest()
    assert records[0]["spec_ref"] == records[1]["spec_ref"] == expected
    assert records[1]["spec"] is None
    assert sys.get_int_max_str_digits() == before


def test_audit_specs_resist_sink_and_consumer_mutation() -> None:
    """ARCH-006: all retained content and its serialized reference stay immutable."""
    import pickle

    engine = _rejecting_engine(["a"])
    stream = io.StringIO()
    writer = ProofAuditWriter(stream)
    seen = []

    def sink(failure):
        seen.append(failure)
        writer(failure)
        with pytest.raises(TypeError):
            failure.spec["values"][0] = "CORRUPTED"
        with pytest.raises(TypeError):
            failure.spec["type"] = "changed"

    engine.set_proof_failure_sink(sink)
    assert list(engine) == ["a"] * 3
    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    original = records[0]["spec"]
    assert all(failure.spec == original for failure in engine.proof_failures)
    assert all(failure.spec == original for failure in seen)
    assert records[0]["spec_ref"] == proofaudit._spec_reference(original)
    assert all(record["spec_ref"] == records[0]["spec_ref"] for record in records)
    restored = pickle.loads(pickle.dumps(seen[0]))
    assert restored.spec == original
    with pytest.raises(TypeError):
        restored.spec["values"][0] = "changed"

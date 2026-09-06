"""Proof tracing follows row sampling without changing generation or validation."""

from __future__ import annotations

from collections.abc import Mapping
from random import Random
from typing import Any
from unittest import mock

import pytest

from ton import api
from ton._proof import TransformStep, _trace_enabled
from ton._transforms import BaseTransform, TransformProof, TransformResult
from ton.generators.base import ChildPipelineGenerator, _GeneratedChildValue


class RecordingTransform(BaseTransform):
    type_name = "record"

    def __init__(self) -> None:
        self.proven: list[str] = []

    def apply(self, prepared: Any, value: TransformResult, rng: Random) -> TransformResult:
        return TransformResult(f"{value.value}:{rng.randrange(100)}")

    def prove(
        self, prepared: Any, before: TransformResult, after: TransformResult
    ) -> TransformProof:
        self.proven.append(after.value)
        return TransformProof(ok=after.value.startswith(before.value + ":"))


class RecordingValidator:
    type_name = "record"

    def __init__(self) -> None:
        self.values: list[str] = []

    def validate(self, value: str) -> bool:
        self.values.append(value)
        return bool(value)


def _nested_config(rows: int = 10) -> dict[str, Any]:
    child = {
        "type": "integer",
        "minValue": 1,
        "maxValue": 9,
        "transforms": [{"type": "record"}],
        "validators": ["record"],
    }
    field = {
        "type": "oneOf",
        "choices": [child],
        "transforms": [{"type": "record"}],
        "validators": ["record"],
    }
    return {"rows": rows, "format": "$x$", "types": {"x": field}}


@pytest.mark.parametrize(("mode", "checked_rows"), [("off", 0), ("sample", 3), ("all", 10)])
def test_traces_follow_sampling_without_changing_draws_or_validators(
    mode: str, checked_rows: int
) -> None:
    config = _nested_config()
    expected = list(
        api.generate(
            config,
            seed=7,
            transforms={"record": RecordingTransform()},
            validators={"record": RecordingValidator()},
            proof_mode="all",
        )
    )
    transform, validator = RecordingTransform(), RecordingValidator()
    with (
        mock.patch("ton._engine.TransformStep", wraps=TransformStep) as root_trace,
        mock.patch("ton.generators.base.TransformStep", wraps=TransformStep) as child_trace,
        mock.patch.object(
            _GeneratedChildValue, "__new__", wraps=_GeneratedChildValue.__new__
        ) as child_value,
    ):
        generated = list(
            api.generate(
                config,
                seed=7,
                transforms={"record": transform},
                validators={"record": validator},
                proof_mode=mode,
                proof_sample_rate=3,
            )
        )

    assert generated == expected
    assert validator.values[1::2] == expected
    assert len(validator.values) == 20
    assert len(transform.proven) == checked_rows * 2
    assert root_trace.call_count == child_trace.call_count == child_value.call_count == checked_rows


@pytest.mark.parametrize("mode", ["off", "sample", "all"])
def test_unchecked_nested_rows_still_run_failing_validators(mode: str) -> None:
    config = _nested_config(rows=1)
    validator = mock.Mock(type_name="record")
    validator.validate.return_value = False
    with pytest.raises(api.ValidationError, match="Nested value failed validator"):
        list(
            api.generate(
                config,
                transforms={"record": RecordingTransform()},
                validators={"record": validator},
                proof_mode=mode,
                proof_sample_rate=3,
            )
        )
    validator.validate.assert_called_once()
    assert _trace_enabled.get() is True


def test_trace_context_resets_before_yield_and_preserves_standalone_proofs() -> None:
    transform = RecordingTransform()
    engine = api.Engine.from_config(
        _nested_config(rows=1),
        transforms={"record": transform},
        validators={"record": RecordingValidator()},
    )
    rows = iter(engine)
    next(rows)
    assert _trace_enabled.get() is True
    rows.close()

    child, prepared = engine._plan.prepared["x"].source_prepared.children[0]
    assert isinstance(child, ChildPipelineGenerator)
    result = child.generate(prepared, Random(0))
    assert isinstance(result, _GeneratedChildValue)
    assert child.prove(prepared, TransformResult(result)).ok
    assert transform.proven == [result]


class ReentrantGenerator(api.Generator):
    type_name = "reentrant"

    def generate(self, prepared: Mapping[str, Any], rng: Random) -> str:
        return next(
            api.generate(
                _nested_config(rows=1),
                seed=rng.randrange(100),
                transforms={"record": RecordingTransform()},
                validators={"record": RecordingValidator()},
                proof_mode="off",
            )
        )


def test_nested_engine_restores_the_parent_proof_decision() -> None:
    config = _nested_config(rows=1)
    config["types"]["x"]["choices"][0] = {"type": "reentrant", "transforms": [{"type": "record"}]}
    transform = RecordingTransform()
    rows = list(
        api.generate(
            config,
            registry={
                "oneOf": api.build_extension_catalog().get_data_type("oneOf"),
                "reentrant": ReentrantGenerator(),
            },
            transforms={"record": transform},
            validators={"record": RecordingValidator()},
            proof_mode="all",
        )
    )
    assert len(rows) == 1
    assert len(transform.proven) == 2
    assert _trace_enabled.get() is True

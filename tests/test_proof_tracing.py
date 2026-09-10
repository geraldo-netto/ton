"""Proof tracing follows row sampling without changing generation or validation."""

from __future__ import annotations

from collections.abc import Mapping
from random import Random
from typing import Any
from unittest import mock

import pytest

from ton import api
from ton._pipeline import ChildPipelineGenerator, _GeneratedChildValue
from ton._proof import TransformStep, _trace_enabled
from ton._transforms import BaseTransform, TransformProof, TransformResult


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
    engine = api.Engine.from_config(
        config,
        seed=7,
        transforms={"record": transform},
        validators={"record": validator},
        proof_mode=mode,
        proof_sample_rate=3,
    )
    field = engine._plan.prepared["x"]
    with (
        mock.patch("ton._engine.TransformStep", wraps=TransformStep) as root_trace,
        mock.patch("ton._pipeline.TransformStep", wraps=TransformStep) as child_trace,
        mock.patch.object(
            _GeneratedChildValue, "__new__", wraps=_GeneratedChildValue.__new__
        ) as child_value,
    ):
        generated = list(engine)

    assert generated == expected
    assert field.validators[0].values[1::2] == expected
    assert len(field.validators[0].values) == 20
    assert len(field.transforms[0].transform.proven) == checked_rows * 2
    assert validator.values == transform.proven == []  # ARCH-030: supplied objects are prototypes.
    assert root_trace.call_count == child_trace.call_count == child_value.call_count == checked_rows


@pytest.mark.parametrize("mode", ["off", "sample", "all"])
def test_unchecked_nested_rows_still_run_failing_validators(mode: str) -> None:
    config = _nested_config(rows=1)
    validator = mock.Mock(type_name="record")
    validator.validate.return_value = False
    engine = api.Engine.from_config(
        config,
        transforms={"record": RecordingTransform()},
        validators={"record": validator},
        proof_mode=mode,
        proof_sample_rate=3,
    )
    with pytest.raises(api.ValidationError, match="Nested value failed validator"):
        list(engine)
    engine._plan.prepared["x"].validators[0].validate.assert_called_once()
    validator.validate.assert_not_called()
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
    assert prepared.transforms[0].transform.proven == [result]
    assert transform.proven == []


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
    engine = api.Engine.from_config(
        config,
        registry={
            "oneOf": api.build_extension_catalog().get_data_type("oneOf"),
            "reentrant": ReentrantGenerator(),
        },
        transforms={"record": transform},
        validators={"record": RecordingValidator()},
        proof_mode="all",
    )
    rows = list(engine)
    assert len(rows) == 1
    assert len(engine._plan.prepared["x"].transforms[0].transform.proven) == 2
    assert transform.proven == []
    assert _trace_enabled.get() is True


@pytest.mark.parametrize("kind", ["oneOf", "weighted", "sequence_of", "distribution"])
@pytest.mark.parametrize("mode, checked", [("off", 0), ("sample", 1), ("all", 3)])
def test_plain_composites_allocate_traces_only_on_checked_rows(kind, mode, checked) -> None:
    """PERF-039: plain composite children follow the row's sampling decision too."""
    from ton._pipeline import ChildDraw, DrawnValue

    child = {"type": "integer", "minValue": 0, "maxValue": 100}
    choices = [{"spec": child}, {"spec": child}]
    fields = {
        "oneOf": {"type": "oneOf", "choices": [child]},
        "weighted": {"type": "weighted", "choices": choices},
        "sequence_of": {"type": "sequence_of", "count": 100, "spec": child},
        "distribution": {**child, "transforms": [{"type": "distribution", "choices": choices}]},
    }
    config = {"rows": 3, "format": "$x$", "types": {"x": fields[kind]}}
    expected = list(api.generate(config, seed=12, proof_mode="all"))
    with (
        mock.patch("ton._pipeline.ChildDraw", wraps=ChildDraw) as draws,
        mock.patch("ton.generators.sequence_of.ChildDraw", wraps=ChildDraw) as sequence_draws,
        mock.patch.object(DrawnValue, "__new__", wraps=DrawnValue.__new__) as values,
    ):
        actual = list(api.generate(config, seed=12, proof_mode=mode, proof_sample_rate=2))
    assert actual == expected
    assert values.call_count == checked
    assert draws.call_count + sequence_draws.call_count == checked * (
        100 if kind == "sequence_of" else 1
    )
    assert _trace_enabled.get() is True


def test_interrupted_composite_unwinds_work_stack_and_trace_context() -> None:
    """SCALE-007: an interruption closes nested tasks and restores caller state."""

    class Interrupted(api.Generator):
        def generate(self, prepared, rng):
            raise KeyboardInterrupt

    registry = api.build_extension_catalog().generators()
    registry["interrupt"] = Interrupted()
    config = {
        "rows": 1,
        "format": "$x$",
        "types": {"x": {"type": "oneOf", "choices": [{"type": "interrupt"}]}},
    }
    engine = api.Engine(config, registry=registry, proof_mode="all")
    with pytest.raises(KeyboardInterrupt):
        list(engine)
    assert _trace_enabled.get() is True
    assert engine.rows_emitted == 0
    assert engine._iteration_lock.acquire(blocking=False)
    engine._iteration_lock.release()

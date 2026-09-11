"""SCALE-024: nested proof metadata shares unchanged text payloads."""

import copy
import pickle
import tracemalloc
from random import Random

import pytest

from ton import api


def _nested(depth, payload, pipelines=False):
    field = {"type": "string", "values": [payload]}
    for _ in range(depth):
        field = {"type": "oneOf", "choices": [field]}
        if pipelines:
            field["transforms"] = [{"type": "identity"}]
    return {"rows": 1, "format": "$x$", "types": {"x": field}}


@pytest.mark.parametrize("pipelines", [False, True])
def test_passthrough_trace_memory_does_not_multiply_payload_by_depth(pipelines):
    peaks = []
    payload = "x" * 100000
    for depth in [10, 80]:
        engine = api.Engine.from_config(_nested(depth, payload, pipelines), proof_mode="all")
        tracemalloc.start()
        try:
            assert list(engine) == [payload]
            peaks.append(tracemalloc.get_traced_memory()[1])
        finally:
            tracemalloc.stop()
    assert peaks[1] < peaks[0] * 3, peaks
    assert peaks[1] < 1000000


@pytest.mark.parametrize("clone", [copy.deepcopy, lambda value: pickle.loads(pickle.dumps(value))])
@pytest.mark.parametrize("pipelines", [False, True])
def test_nested_trace_roundtrip_retains_ownership_and_payload_sharing(clone, pipelines):
    engine = api.Engine.from_config(_nested(8, "payload" * 1000, pipelines), proof_mode="all")
    field = engine._plan.prepared["x"]
    value = field.generator.generate(field.source_prepared, Random(42))
    assert isinstance(value, str)
    copied_field, copied_value = clone((field, value))
    assert copied_value == value
    assert copied_field.generator.prove(
        copied_field.source_prepared, api.TransformResult(copied_value)
    ).ok


def test_replacing_traced_result_text_cannot_reuse_its_old_draws():
    """SCALE-024: detached metadata must stay bound to its exact string payload."""
    from dataclasses import replace

    from ton._pipeline import as_result
    from ton._steps import run_steps

    engine = api.Engine.from_config(_nested(3, "actual"))
    field = engine._plan.prepared["x"]
    value = run_steps(field.generator, "generate", field.source_prepared, Random(42))
    result = as_result(value)
    assert field.generator.prove(field.source_prepared, result).ok
    assert not field.generator.prove(field.source_prepared, replace(result, value="forged")).ok


def test_internal_passthrough_traces_share_the_same_string_object():
    from ton._pipeline import DrawTrace, PipelineTrace
    from ton._steps import run_steps
    from ton._tracetext import TraceText

    engine = api.Engine.from_config(_nested(80, "payload" * 1000, True))
    field = engine._plan.prepared["x"]
    value = run_steps(field.generator, "generate", field.source_prepared, Random(42))
    payload = value.value
    pending = [value]
    seen = set()
    count = 0
    while pending:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        if not isinstance(item, TraceText):
            assert item is payload
            continue
        assert item.value is payload
        count += 1
        trace = item.trace
        if isinstance(trace, DrawTrace):
            pending.extend(draw.value for draw in trace.draws)
        else:
            assert isinstance(trace, PipelineTrace)
            pending.append(trace.source._trace or trace.source.value)
            for step in trace.steps:
                pending.extend(
                    (step.before._trace or step.before.value, step.after._trace or step.after.value)
                )
    assert count == 159


@pytest.mark.parametrize("clone", [copy.deepcopy, lambda value: pickle.loads(pickle.dumps(value))])
def test_standalone_child_pipeline_trace_roundtrip(clone):
    from ton._pipeline import _GeneratedChildValue

    engine = api.Engine.from_config(_nested(2, "value", True))
    field = engine._plan.prepared["x"]
    child, prepared = field.source_prepared.children[0]
    value = child.generate(prepared, Random(42))
    assert isinstance(value, _GeneratedChildValue)
    prepared, value = clone((prepared, value))
    assert child.prove(prepared, api.TransformResult(value)).ok


def test_public_transform_result_drops_stale_trace_on_changed_text():
    from dataclasses import replace

    from ton._pipeline import as_result, public_result
    from ton._steps import run_steps

    engine = api.Engine.from_config(_nested(2, "actual"))
    field = engine._plan.prepared["x"]
    value = run_steps(field.generator, "generate", field.source_prepared, Random(42))
    changed = replace(as_result(value), value="changed")
    assert public_result(changed) is changed
    assert not field.generator.prove(field.source_prepared, public_result(changed)).ok

"""Permanent work/allocation regressions for performance and scalability findings."""

import pytest

from ton._specsnapshot import snapshot_spec


@pytest.mark.parametrize("immutable", [False, True])
@pytest.mark.parametrize("kind", ["mapping", "sequence"])
def test_snapshot_does_not_queue_all_siblings_before_visiting_children(kind, immutable):
    """SCALE-021: source traversal applies backpressure at each active container."""
    visited = 0

    class Child(dict):
        def items(self):
            nonlocal visited
            visited += 1
            return super().items()

    values = [Child(value=index) for index in range(1000)]

    def children():
        for index, child in enumerate(values):
            assert visited == index, "snapshot eagerly queued unprocessed siblings"
            yield child

    class WideList(list):
        def __iter__(self):
            return children()

    class WideMapping(dict):
        def items(self):
            return ((str(index), child) for index, child in enumerate(children()))

    source = (
        WideList(values)
        if kind == "sequence"
        else WideMapping(zip(map(str, range(1000)), values, strict=True))
    )
    copied = snapshot_spec(source, immutable=immutable)
    assert visited == 1000
    assert len(copied) == 1000
    key = 999 if kind == "sequence" else "999"
    assert copied[key]["value"] == 999


@pytest.mark.parametrize("worker", [False, True])
def test_generation_does_not_visit_or_retain_unused_field_contents(worker, caplog):
    """SCALE-025: inactive data is untouched; full validation remains explicit."""
    import logging

    from ton import api

    class UnusedPool(list):
        def __iter__(self):
            raise AssertionError("unused pool was traversed")

    field = {"type": "string", "values": ["original"]}
    config = {
        "rows": 1,
        "format": "$x$:$y$",
        "types": {
            "x": field,
            "y": field,
            "unused": {"type": "string", "values": UnusedPool(["z"])},
        },
    }
    with caplog.at_level(logging.INFO, logger="ton"):
        engine = (
            api.fork_engine(config, parent_seed=42, worker_id=0) if worker else api.Engine(config)
        )
    assert set(engine._plan.types) == {"x", "y"}
    if not worker:
        assert engine._plan.types["x"] is engine._plan.types["y"]
    field["values"].append("changed")
    assert list(engine) == ["original:original"]
    constructed = next(
        r for r in caplog.records if getattr(r, "event", None) == "engine_constructed"
    )
    assert constructed.types == 3
    with pytest.raises(AssertionError, match="unused pool was traversed"):
        api.validate_config(config)


def test_compile_path_storage_grows_linearly_with_depth():
    """SCALE-019: compare allocation growth, independent of elapsed machine time."""
    import gc
    import tracemalloc

    from ton import api

    peaks = []
    for depth in (500, 1000):
        spec = {"type": "sequence"}
        for _ in range(depth):
            spec = {"type": "sequence_of", "count": 1, "spec": spec}
        config = {"rows": 0, "format": "$x$", "types": {"x": spec}}
        gc.collect()
        tracemalloc.start()
        try:
            engine = api.Engine(config)
            peaks.append(tracemalloc.get_traced_memory()[1])
        finally:
            tracemalloc.stop()
        assert engine.total_rows == 0
        del engine
    assert peaks[1] < peaks[0] * 2.8, peaks


@pytest.mark.parametrize(
    "bounds", [(0, "1e-1000000"), ("-1e-1000000", 0), ("0e1000000", "0e1000000"), ("0e-1000000", 0)]
)
def test_small_decimal_results_do_not_allocate_exponent_sized_integers(bounds):
    """SCALE-022: compact tiny/zero bounds keep constant-sized rounding work."""
    import tracemalloc
    from decimal import localcontext
    from random import Random

    from ton._transforms import TransformResult
    from ton.generators.decimal import DecimalGenerator

    generator = DecimalGenerator()
    with localcontext() as context:
        context.prec, context.Emax, context.Emin = 2, 2, -2
        prepared = generator.prepare({"minValue": bounds[0], "maxValue": bounds[1], "decimals": 0})
        rng = Random(42)
        tracemalloc.start()
        try:
            value = generator.generate(prepared, rng)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert value == "0"
        assert generator.prove(prepared, TransformResult(value)).ok
        assert peak < 64000, peak


@pytest.mark.parametrize("value", ["1e-1000000", "-1e-1000000"])
def test_tiny_nonzero_singleton_has_no_integer_representation(value):
    """SCALE-022: fast rounding cannot turn an empty interval into a valid job."""
    from ton.generators.decimal import DecimalGenerator

    with pytest.raises(ValueError, match="no value representable"):
        DecimalGenerator().prepare({"minValue": value, "maxValue": value, "decimals": 0})


def test_compact_paths_preserve_components_hash_collisions_and_serialization():
    """SCALE-019: tuple boundaries remain distinct and equality checks hash collisions."""
    import pickle

    from ton._specpath import SpecLocation

    root = SpecLocation()
    location = root + ("a.b", 0)
    assert not root and bool(location)
    assert tuple(location) == ("a.b", 0)
    assert location == SpecLocation() + ("a.b", 0)
    assert location != root + ("a", "b", 0)
    assert location != ("a.b", 0)
    assert location != root + ("other", 0)
    assert repr(location) == "'a.b[0]'"
    assert {location: "value"}[pickle.loads(pickle.dumps(location))] == "value"

    class Colliding(str):
        def __hash__(self):
            return 0

    left, right = root + (Colliding("left"),), root + (Colliding("right"),)
    assert hash(left) == hash(right)
    assert left != right


def test_worker_path_storage_grows_linearly_with_depth():
    """SCALE-020: partition traversal does not retain every full diagnostic string."""
    import gc
    import tracemalloc

    from ton._registry import default_transforms, make_registry
    from ton.concurrency import _offset_sequence_spec

    registry, transforms = make_registry(), default_transforms()
    peaks = []
    for depth in (500, 1000):
        spec = {"type": "sequence"}
        for _ in range(depth):
            spec = {"type": "sequence_of", "count": 1, "spec": spec}
        gc.collect()
        tracemalloc.start()
        try:
            shifted = _offset_sequence_spec(spec, 7, registry, transforms, path="types.x")
            peaks.append(tracemalloc.get_traced_memory()[1])
        finally:
            tracemalloc.stop()
        for _ in range(depth):
            shifted = shifted["spec"]
        assert shifted["start"] == 7
    assert peaks[1] < peaks[0] * 2.8, peaks

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

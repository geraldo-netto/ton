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

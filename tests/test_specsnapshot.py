"""Ownership and identity regressions for configuration snapshots."""

from collections.abc import Mapping, Sequence

import pytest

from ton import api
from ton._specsnapshot import snapshot_spec


class ComputedMapping(Mapping):
    def __len__(self):
        return 100

    def __iter__(self):
        return iter(range(len(self)))

    def __getitem__(self, key):
        return {"value": key}


class ComputedSequence(Sequence):
    def __len__(self):
        return 100

    def __getitem__(self, key):
        if key >= len(self):
            raise IndexError(key)
        return {"value": key}


@pytest.mark.parametrize("immutable", [False, True])
@pytest.mark.parametrize("source", [ComputedMapping, ComputedSequence])
def test_computed_children_do_not_acquire_false_aliases(source, immutable):
    """REL-057: temporary children must survive identity-based memoization."""
    copied = snapshot_spec(source(), immutable=immutable)
    assert [copied[key]["value"] for key in range(100)] == list(range(100))
    assert len({id(copied[key]) for key in range(100)}) == 100


def test_engine_preserves_computed_plugin_metadata():
    """REL-057: snapshotting lazy plugin metadata preserves every child value."""

    class Computed(api.Generator):
        def generate(self, prepared, rng):
            return ",".join(str(child["value"]) for child in prepared["metadata"].values())

    config = {
        "rows": 1,
        "format": "$x$",
        "types": {"x": {"type": "computed", "metadata": ComputedMapping()}},
    }
    assert list(api.generate(config, registry={"computed": Computed()})) == [
        ",".join(map(str, range(100)))
    ]

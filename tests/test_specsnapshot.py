"""Ownership and identity regressions for configuration snapshots."""

from collections.abc import Mapping, Sequence
from types import SimpleNamespace

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


@pytest.mark.parametrize("immutable", [False, True])
def test_opaque_metadata_copies_share_the_snapshot_memo(immutable):
    """REL-059: opaque state preserves cycles/forward aliases in the owned graph."""
    blob = bytearray(b"original")
    state = SimpleNamespace(blob=blob, labels={"original"})
    forward = {"state": state}
    source = {"state": state, "blob": blob, "forward": forward}
    state.root = source
    state.forward = forward
    copied = snapshot_spec(source, immutable=immutable)
    assert copied["state"] is not state
    assert copied["state"].root is copied
    assert copied["state"].forward is copied["forward"]
    assert copied["forward"]["state"] is copied["state"]
    assert copied["state"].blob is copied["blob"]
    blob[:] = b"changed"
    state.labels.add("changed")
    assert copied["blob"] == bytearray(b"original")
    assert copied["state"].labels == {"original"}


def test_engine_and_audit_isolate_opaque_plugin_state():
    """REL-059: caller, Engines and audit sinks cannot mutate each other's state."""

    class Blob(api.Generator):
        def generate(self, prepared, rng):
            return prepared["blob"].decode()

        def prove(self, prepared, result):
            return api.ProofResult(False, "rejected")

    blob = bytearray(b"original")
    config = {"rows": 2, "format": "$x$", "types": {"x": {"type": "blob", "blob": blob}}}
    first = api.Engine(config, registry={"blob": Blob()}, proof_mode="audit")
    second = api.Engine(config, registry={"blob": Blob()})
    blob[:] = b"caller"
    iterator = iter(first)
    assert next(iterator) == "original"
    first.proof_failures[0].spec["blob"][:] = b"sink"
    assert list(iterator) == ["original"]
    assert list(second) == ["original", "original"]
    assert blob == bytearray(b"caller")


def test_uncopyable_opaque_metadata_has_a_clear_error():
    """REL-059: unsupported ownership must fail instead of silently sharing state."""

    class Uncopyable:
        def __deepcopy__(self, memo):
            raise TypeError("resource cannot be copied")

    with pytest.raises(ValueError, match="Cannot snapshot opaque config value.*Uncopyable"):
        snapshot_spec({"metadata": Uncopyable()})

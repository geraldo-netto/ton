"""Declared ownership retains physical occurrences and extension context."""

from ton import api
from ton._specgraph import field_ownership


def test_ownership_keeps_alias_occurrences_and_opaque_metadata():
    """ARCH-028: both consumers see the same paths and owners, including aliases."""
    snapshot = api.build_extension_catalog().snapshot()
    child = {"type": "string", "values": ["x"]}
    transform_spec = {"type": "distribution", "choices": [{"spec": child}, {"spec": child}]}
    spec = {
        "type": "oneOf",
        "choices": [child, child],
        "metadata": {"type": "sequence"},
        "transforms": [transform_spec],
    }
    generator = snapshot.generators["oneOf"]
    ownership = field_ownership(spec, generator, snapshot.transforms)
    assert not ownership.uses_source
    assert [owned.location for owned in ownership.source_children] == [
        ("choices", 0),
        ("choices", 1),
    ]
    assert [owned.location for owned in ownership.transform_children] == [
        ("transforms", 0, "choices", 0, "spec"),
        ("transforms", 0, "choices", 1, "spec"),
    ]
    for owned in ownership.source_children:
        assert owned.spec is child
        assert owned.owner is generator
        assert owned.owner_spec is spec
    for owned in ownership.transform_children:
        assert owned.spec is child
        assert owned.owner is snapshot.transforms["distribution"]
        assert owned.owner_spec is transform_spec
    active = field_ownership(spec, generator, snapshot.transforms, include_inactive_source=False)
    assert active.source_children == ()
    assert active.transform_children == ownership.transform_children

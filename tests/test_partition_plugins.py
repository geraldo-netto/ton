"""Worker partitioning follows extension-owned child draw multiplicities."""

from copy import deepcopy
from itertools import count

import pytest

from ton import api


class Repeat(api.Generator):
    type_name = "repeat"
    config_keys = frozenset({"count", "spec"})

    def nested_specs(self, spec):
        return ((("spec",), spec["spec"]),)

    def prepare(self, spec, context=None):
        return context.prepare_child(self.type_name, ("spec",), spec["spec"]), spec["count"]

    def generate(self, prepared, rng):
        (generator, child), amount = prepared
        return ",".join(generator.generate(child, rng) for _ in range(amount))

    def partition(self, spec, offset):
        return api.PartitionSpec(child_offsets={("spec",): offset * spec["count"]})


class RepeatTransform:
    type_name = "repeat_transform"
    config_keys = Repeat.config_keys
    capabilities = api.TransformCapabilities()
    requires_source = False
    nested_specs = Repeat.nested_specs
    prepare = Repeat.prepare
    partition = Repeat.partition

    def apply(self, prepared, value, rng):
        return api.TransformResult(Repeat().generate(prepared, rng))

    def prove(self, prepared, before, after):
        return api.TransformProof(True)


class OffsetCounter(api.Generator):
    type_name = "offset_counter"
    config_keys = frozenset({"start", "step"})

    def __init__(self):
        self.partition_calls = 0

    def prepare(self, spec, context=None):
        return count(spec["start"], spec["step"])

    def generate(self, prepared, rng):
        return str(next(prepared))

    def partition(self, spec, offset):
        self.partition_calls += 1
        return api.PartitionSpec(updates={"start": spec["start"] + offset * spec["step"]})


@pytest.mark.parametrize("leaf", ["sequence", "core.sequence", "example.counter"])
@pytest.mark.parametrize("kind", ["generator", "transform", "nested"])
def test_extension_partitioning_respects_nested_multiplicity(leaf, kind):
    """ARCH-033: custom parents reserve disjoint sequence ranges across uneven shards."""
    catalog = api.build_extension_catalog()
    counter = OffsetCounter()
    catalog.register_data_type("example", "counter", counter)
    catalog.register_data_type("example", "repeat", Repeat())
    catalog.register_transform("example", "repeat", RepeatTransform())
    snapshot = catalog.snapshot()
    child = {"type": leaf, "start": 100, "step": 3}
    if kind != "generator":
        child = {
            "type": "string",
            "values": ["unused"],
            "transforms": [
                {"type": "example.repeat", "count": 2, "spec": child},
            ],
        }
    if kind != "transform":
        child = {"type": "example.repeat", "count": 3, "spec": child}
    config = {"rows": 7, "format": "$x$|$x$", "types": {"x": child}}
    original = deepcopy(config)
    values = []
    for worker in range(3):
        engine = api.fork_engine(
            config,
            parent_seed=42,
            worker_id=worker,
            workers=3,
            rows=api.chunk_rows(7, 3, worker),
            options=api.EngineOptions(registry=snapshot.generators, transforms=snapshot.transforms),
        )
        for row in engine:
            values.extend(int(value) for value in row.replace("|", ",").split(","))
    draws = {"generator": 3, "transform": 2, "nested": 6}[kind]
    assert values == list(range(100, 100 + 3 * 7 * 2 * draws, 3))
    assert len(set(values)) == len(values)
    assert config == original
    assert counter.partition_calls == 0
    assert snapshot.generators["example.counter"].partition_calls == 0


def test_leaf_transform_partitions_its_own_settings():
    """ARCH-033: partition hooks also apply to transforms with no generator children."""

    class CounterTransform(RepeatTransform):
        config_keys = frozenset({"start"})

        def nested_specs(self, spec):
            return ()

        def prepare(self, spec, context):
            return count(spec["start"])

        def apply(self, prepared, value, rng):
            return api.TransformResult(str(next(prepared)))

        def partition(self, spec, offset):
            return api.PartitionSpec(updates={"start": spec["start"] + offset})

    config = {
        "rows": 4,
        "format": "$x$",
        "types": {
            "x": {
                "type": "string",
                "values": ["unused"],
                "transforms": [{"type": "example.counter", "start": 100}],
            }
        },
    }
    rows = []
    for worker in range(2):
        rows.extend(
            api.fork_engine(
                config,
                parent_seed=0,
                worker_id=worker,
                workers=2,
                rows=2,
                options=api.EngineOptions(transforms={"example.counter": CounterTransform()}),
            )
        )
    assert rows == ["100", "101", "102", "103"]
    assert config["types"]["x"]["transforms"][0]["start"] == 100


@pytest.mark.parametrize(
    "plan,error",
    [
        (None, "must return PartitionSpec"),
        (api.PartitionSpec(updates={"type": "sequence"}), "cannot replace"),
        (api.PartitionSpec(updates={"spec": {"type": "sequence"}}), "cannot replace"),
        (api.PartitionSpec(child_offsets={("missing",): 2}), "declared child locations"),
        (api.PartitionSpec(child_offsets={("spec",): True}), "non-negative integers"),
        (api.PartitionSpec(child_offsets={("spec",): -1}), "non-negative integers"),
        (api.PartitionSpec(child_offsets={("spec",): 1.5}), "non-negative integers"),
    ],
)
def test_partition_contract_rejects_invalid_hook_results(plan, error):
    """ARCH-033: malformed capabilities cannot silently produce overlapping shards."""

    class InvalidPartition(Repeat):
        def partition(self, spec, offset):
            return plan

    registry = api.build_extension_catalog().generators()
    registry["example.repeat"] = InvalidPartition()
    config = {
        "rows": 1,
        "format": "$x$",
        "types": {
            "x": {
                "type": "example.repeat",
                "count": 2,
                "spec": {"type": "sequence"},
            }
        },
    }
    with pytest.raises((TypeError, ValueError), match=error):
        api.fork_engine(
            config, parent_seed=0, worker_id=0, options=api.EngineOptions(registry=registry)
        )


@pytest.mark.parametrize("replaced", [False, True])
def test_partition_offsets_follow_paired_source_caching(replaced):
    """ARCH-033: cached pairs draw once per row; source-replacing transforms do not."""

    class PairCounter(api.PairedGenerator):
        type_name = "paired_counter"
        __init__ = OffsetCounter.__init__
        prepare = OffsetCounter.prepare
        partition = OffsetCounter.partition

        def generate_pair(self, prepared, rng):
            value = str(next(prepared))
            return "id-" + value, value

    snapshot = api.build_extension_catalog().snapshot()
    registry = {**snapshot.generators, "example.pair": PairCounter()}
    spec = {"type": "example.pair", "start": 100, "step": 1}
    if replaced:
        spec["transforms"] = [
            {"type": "example.repeat", "count": 1, "spec": {"type": "sequence", "start": 100}}
        ]
    config = {"rows": 4, "format": "$x$|$x$", "types": {"x": spec}}
    rows = []
    for worker in range(2):
        rows.extend(
            api.fork_engine(
                config,
                parent_seed=0,
                worker_id=worker,
                workers=2,
                rows=2,
                options=api.EngineOptions(
                    registry=registry, transforms={"example.repeat": RepeatTransform()}
                ),
            )
        )
    if replaced:
        assert rows == ["100|101", "102|103", "104|105", "106|107"]
    else:
        assert rows == ["100|100", "101|101", "102|102", "103|103"]

"""Shared plugin dependencies and per-engine runtime ownership."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import MappingProxyType

import pytest

from ton import api


class Issuer(api.Generator):
    type_name = "issuer"

    def __init__(self, issued):
        self.issued = issued

    def generate(self, prepared, rng):
        self.issued.add("issued")
        return "issued"


class IssuedValidator:
    type_name = "issued"

    def __init__(self, issued):
        self.issued = issued

    def validate(self, value):
        return value in self.issued


class IssuedTransform:
    type_name = "mark"
    config_keys = frozenset()
    capabilities = api.TransformCapabilities()
    requires_source = True

    def __init__(self, issued):
        self.issued = issued

    def nested_specs(self, spec):
        return ()

    def prepare(self, spec, context):
        return None

    def apply(self, prepared, value, rng):
        assert value.value in self.issued
        result = value.value + "!"
        self.issued.add(result)
        return api.TransformResult(result)

    def prove(self, prepared, before, after):
        return api.TransformProof(after.value == before.value + "!")


def issued_catalog():
    issued = set()
    catalog = api.build_extension_catalog()
    catalog.register_data_type("example", "issuer", Issuer(issued))
    catalog.register_transform("example", "mark", IssuedTransform(issued))
    catalog.register_validator("example", "issued", IssuedValidator(issued))
    return catalog


def test_catalog_snapshot_retains_cross_kind_dependencies():
    """ARCH-029: one snapshot preserves shared dependencies across plugin kinds."""
    catalog = issued_catalog()
    first = catalog.snapshot()
    second = catalog.snapshot()
    assert first.generators["example.issuer"].issued is first.validators["example.issued"].issued
    assert first.generators["example.issuer"].issued is first.transforms["example.mark"].issued
    assert (
        first.generators["example.issuer"].issued is not second.generators["example.issuer"].issued
    )
    config = {
        "rows": 1,
        "format": "$x$",
        "types": {
            "x": {
                "type": "example.issuer",
                "validators": ["example.issued"],
                "transforms": [{"type": "example.mark"}],
            },
        },
    }
    assert list(
        api.generate(
            config,
            registry=first.generators,
            transforms=first.transforms,
            validators=first.validators,
            proof_mode="all",
        )
    ) == ["issued!"]
    assert not second.validators["example.issued"].validate("issued!")
    assert first.generators["integer"] is first.generators["core.integer"]
    assert first.transforms["identity"] is first.transforms["core.identity"]
    assert first.validators["non_empty"] is first.validators["core.non_empty"]


def test_catalog_snapshot_waits_for_catalog_mutation_lock():
    """ARCH-029: a reader cannot observe a catalog while another owner mutates it."""
    catalog = issued_catalog()
    started, finished = Event(), Event()

    def snapshot():
        started.set()
        result = catalog.snapshot()
        finished.set()
        return result

    with ThreadPoolExecutor(max_workers=1) as pool:
        with catalog._lock:
            future = pool.submit(snapshot)
            assert started.wait(timeout=5)
            assert not finished.wait(timeout=0.05)
            catalog.register_validator("example", "new", IssuedValidator(set()))
        result = future.result(timeout=5)
    assert "example.new" in result.validators


class Counter(api.Generator):
    type_name = "counter"

    def __init__(self):
        self.count = 0

    def generate(self, prepared, rng):
        value = self.count
        self.count += 1
        return str(value)


class CountingTransform(IssuedTransform):
    type_name = "count"

    def __init__(self):
        self.count = 0

    def apply(self, prepared, value, rng):
        result = api.TransformResult(f"{value.value}:{self.count}")
        self.count += 1
        return result


class TwoRowsValidator:
    type_name = "two_rows"

    def __init__(self):
        self.count = 0

    def validate(self, value):
        self.count += 1
        return self.count <= 2


@pytest.mark.parametrize("mapping", [dict, MappingProxyType])
@pytest.mark.parametrize("worker", [False, True])
def test_engine_construction_owns_supplied_extension_state(mapping, worker):
    """ARCH-030: reused input mappings/options are prototypes, not shared runtime state."""
    generator, transform, validator = Counter(), CountingTransform(), TwoRowsValidator()
    options = api.EngineOptions(
        registry=mapping({"example.counter": generator}),
        transforms=mapping({"example.count": transform}),
        validators=mapping({"example.two_rows": validator}),
        seed=42,
    )
    config = {
        "rows": 2,
        "format": "$x$",
        "types": {
            "x": {
                "type": "example.counter",
                "transforms": [{"type": "example.count"}],
                "validators": ["example.two_rows"],
            }
        },
    }

    def build(index):
        if worker:
            return api.fork_engine(
                config,
                parent_seed=42,
                worker_id=index,
                options=api.EngineOptions(
                    registry=options.registry,
                    transforms=options.transforms,
                    validators=options.validators,
                ),
            )
        return api.Engine.from_options(config, options)

    first, second = build(0), build(1)
    assert list(first) == ["0:0", "1:1"]
    assert list(second) == ["0:0", "1:1"]
    assert list(build(2)) == ["0:0", "1:1"]
    assert generator.count == transform.count == validator.count == 0

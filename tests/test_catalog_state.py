"""Shared plugin dependencies and per-engine runtime ownership."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

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

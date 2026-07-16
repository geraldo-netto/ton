"""Tests for the auto-discovering registry."""

from __future__ import annotations

import inspect
import logging
import subprocess
import sys
from random import Random
from typing import Any, ClassVar
from unittest import mock

import pytest

from ton._logging import LogEvent
from ton._registry import (
    ExtensionCatalog,
    RegistryError,
    build_extension_catalog,
    catalog_with_entry_points,
    clear_default_registry_cache,
    default_registry,
    discover_generator_classes,
    normalize_reference,
    registry_with_entry_points,
)
from ton._transforms import BaseTransform
from ton.generators import Generator


@pytest.mark.parametrize(
    "imports",
    [
        "import ton.transforms; import ton.generators",
        "import ton.transforms.distribution; import ton.generators",
        "import ton.generators; import ton.transforms",
        "import ton._registry; ton._registry.default_registry()",
    ],
)
def test_public_packages_import_cleanly_in_fresh_interpreter(imports: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-c", imports],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


#: Every built-in type that ships with TON. If this list grows or
#: shrinks, the registry should reflect it without anyone editing
#: ton/registry.py (TODO DUP-003).
EXPECTED_TYPES = {
    "boolean",
    "bytes",
    "char",
    "date",
    "decimal",
    "email",
    "hash",
    "integer",
    "ipv4",
    "ipv6",
    "lmhash",
    "mac",
    "name",
    "phone",
    "regex",
    "sequence",
    "string",
    "text",
    "timestamp_unix",
    "uuid",
    "weighted",
}


def test_discover_returns_only_concrete_named_subclasses() -> None:
    for cls in discover_generator_classes():
        assert issubclass(cls, Generator)
        assert cls.type_name
        assert not inspect.isabstract(cls)


def test_default_registry_covers_every_expected_type() -> None:
    keys = set(default_registry().keys())
    missing = EXPECTED_TYPES - keys
    assert not missing, f"missing types in registry: {missing}"
    # Extras may show up legitimately when other tests in the same
    # process define their own Generator subclasses for fixtures;
    # discover_generator_classes() walks the live subclass tree, so we
    # only assert that the built-ins are *present*, not that nothing
    # else is.


def test_default_registry_instances_are_independent() -> None:
    first = default_registry()
    second = default_registry()
    # Different Generator instances per call so per-spec state (e.g.
    # SequenceGenerator counters) is not shared across engines.
    assert first["sequence"] is not second["sequence"]


def test_default_registry_class_list_is_cached(monkeypatch) -> None:
    """default_registry() should call discover_generator_classes at most
    once across repeated calls (PERF-008)."""
    import ton._registry as registry_mod

    clear_default_registry_cache()
    calls = {"n": 0}
    real = registry_mod.discover_generator_classes

    def _counting() -> list:
        calls["n"] += 1
        return real()

    monkeypatch.setattr(registry_mod, "discover_generator_classes", _counting)
    default_registry()
    default_registry()
    default_registry()
    assert calls["n"] == 1
    clear_default_registry_cache()  # leave the module in its original state


def test_clear_cache_forces_rediscovery() -> None:
    """Explicit invalidation should re-walk the subclass tree."""
    clear_default_registry_cache()
    first_keys = set(default_registry().keys())
    clear_default_registry_cache()
    second_keys = set(default_registry().keys())
    assert first_keys == second_keys
    assert first_keys >= EXPECTED_TYPES


def test_registry_with_entry_points_includes_builtins() -> None:
    # Without any third-party entry points installed this is identical
    # to default_registry().
    assert set(registry_with_entry_points()) >= EXPECTED_TYPES


def test_registry_with_entry_points_honors_allowlist() -> None:
    class CustomGenerator(Generator):
        type_name = "custom"

        def generate(self, prepared: Any, rng: Random) -> str:
            return "custom"

    allowed = mock.Mock()
    allowed.name = "allowed"
    allowed.value = "pkg:Allowed"
    allowed.load.return_value = CustomGenerator
    skipped = mock.Mock()
    skipped.name = "skipped"
    skipped.value = "pkg:Skipped"

    with mock.patch("ton._registry.entry_points", return_value=[allowed, skipped]):
        registry = registry_with_entry_points(allowed_names={"allowed"})

    assert registry["allowed"].generate({}, Random(0)) == "custom"
    assert registry["plugin.allowed"].generate({}, Random(0)) == "custom"
    skipped.load.assert_not_called()


def test_registry_with_entry_points_does_not_shadow_builtin() -> None:
    class CustomGenerator(Generator):
        type_name = "string"

        def generate(self, prepared: Any, rng: Random) -> str:
            return "custom"

    ep = mock.Mock()
    ep.name = "string"
    ep.value = "pkg:String"
    ep.load.return_value = CustomGenerator

    with mock.patch("ton._registry.entry_points", return_value=[ep]):
        registry = registry_with_entry_points()

    prepared = registry["string"].prepare({"values": ["builtin"]})
    assert registry["string"].generate(prepared, Random(0)) == "builtin"
    assert registry["plugin.string"].generate({}, Random(0)) == "custom"


def test_registry_skips_entry_point_that_returns_non_generator() -> None:
    bad = mock.Mock()
    bad.name = "bad"
    bad.value = "pkg:Bad"
    bad.load.return_value = lambda: object()

    with mock.patch("ton._registry.entry_points", return_value=[bad]):
        registry = registry_with_entry_points()

    assert "bad" not in registry


def test_extension_catalog_registers_namespaced_plugins() -> None:
    class CustomGenerator(Generator):
        type_name = "custom"

        def generate(self, prepared: Any, rng: Random) -> str:
            return "custom"

    class CustomTransform(BaseTransform):
        type_name: ClassVar[str] = "trim"

    catalog = build_extension_catalog()
    catalog.register_data_type("plugin", "custom", CustomGenerator())
    catalog.register_transform("plugin", "trim", CustomTransform())
    catalog.register_validator("plugin", "custom", object())

    assert "string" in catalog.list_data_types()
    assert "core.string" in catalog.list_data_types()
    assert "plugin.custom" in catalog.list_data_types()
    assert "plugin.trim" in catalog.list_transforms()
    assert "plugin.custom" in catalog.list_validators()
    assert catalog.get_data_type("plugin.custom").generate({}, Random(0)) == "custom"
    assert catalog.get_transform("plugin.trim").type_name == "trim"


def test_catalog_caches_flattened_view_until_registration() -> None:
    class CustomGenerator(Generator):
        type_name = "widget"

        def generate(self, prepared: Any, rng: Random) -> str:
            del prepared, rng
            return "w"

    catalog = build_extension_catalog()
    first = catalog.generators()
    assert catalog.generators() is first  # PERF-003: cached identity, not rebuilt

    catalog.register_data_type("acme", "widget", CustomGenerator())

    assert catalog.generators() is not first  # registration invalidated the cache
    assert "acme.widget" in catalog.generators()


def test_extension_catalog_rejects_builtin_replacement() -> None:
    catalog = build_extension_catalog()

    with pytest.raises(RegistryError, match="cannot replace"):
        catalog.register_data_type("core", "string", default_registry()["string"])


def test_core_registration_does_not_emit_plugin_event(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class CustomGenerator(Generator):
        type_name = "custom_core"

        def generate(self, prepared: Any, rng: Random) -> str:
            return "custom"

    catalog = ExtensionCatalog(generators={})

    with caplog.at_level(logging.INFO, logger="ton"):
        catalog.register_data_type("core", "custom_core", CustomGenerator())

    assert not any(
        getattr(record, "event", None) == LogEvent.PLUGIN_REGISTERED.value
        for record in caplog.records
    )


def test_extension_catalog_rejects_ambiguous_registration() -> None:
    class CustomTransform(BaseTransform):
        type_name: ClassVar[str] = "trim"

    catalog = build_extension_catalog()
    catalog.register_transform("plugin", "trim", CustomTransform())

    with pytest.raises(RegistryError, match="already exists"):
        catalog.register_transform("plugin", "trim", CustomTransform())


def test_normalize_reference_defaults_to_core_namespace() -> None:
    assert normalize_reference("integer") == "core.integer"
    assert normalize_reference("plugin.integer") == "plugin.integer"
    with pytest.raises(RegistryError):
        normalize_reference("bad-name")
    with pytest.raises(RegistryError, match="invalid registry reference"):
        normalize_reference("too.many.parts")


def test_catalog_entry_points_load_separate_plugin_kinds() -> None:
    class CustomGenerator(Generator):
        type_name = "custom"

        def generate(self, prepared: Any, rng: Random) -> str:
            return "custom"

    class CustomTransform(BaseTransform):
        type_name: ClassVar[str] = "trim"

    generator_ep = mock.Mock()
    generator_ep.name = "acme.custom"
    generator_ep.value = "pkg:Generator"
    generator_ep.load.return_value = CustomGenerator
    transform_ep = mock.Mock()
    transform_ep.name = "acme.trim"
    transform_ep.value = "pkg:Transform"
    transform_ep.load.return_value = CustomTransform
    validator_ep = mock.Mock()
    validator_ep.name = "acme.custom"
    validator_ep.value = "pkg:Validator"
    validator_ep.load.return_value = lambda: object()

    def _entry_points(group: str):
        return {
            "ton.generators": [generator_ep],
            "ton.transforms": [transform_ep],
            "ton.validators": [validator_ep],
        }[group]

    with mock.patch("ton._registry.entry_points", side_effect=_entry_points):
        catalog = catalog_with_entry_points()

    assert "acme.custom" in catalog.list_data_types()
    assert "acme.trim" in catalog.list_transforms()
    assert "acme.custom" in catalog.list_validators()


def test_catalog_entry_points_honor_allowlist() -> None:
    allowed = mock.Mock()
    allowed.name = "acme.trim"
    allowed.value = "pkg:Transform"
    allowed.load.return_value = BaseTransform
    skipped = mock.Mock()
    skipped.name = "acme.skip"
    skipped.value = "pkg:Skip"

    def _entry_points(group: str):
        return [allowed, skipped] if group == "ton.transforms" else []

    with mock.patch("ton._registry.entry_points", side_effect=_entry_points):
        catalog = catalog_with_entry_points(allowed_names={"acme.trim"})

    assert "acme.trim" in catalog.list_transforms()
    skipped.load.assert_not_called()


def test_catalog_entry_points_skip_wrong_plugin_kind() -> None:
    bad = mock.Mock()
    bad.name = "acme.bad"
    bad.value = "pkg:Bad"
    bad.load.return_value = lambda: object()

    def _entry_points(group: str):
        return [bad] if group == "ton.transforms" else []

    with mock.patch("ton._registry.entry_points", side_effect=_entry_points):
        catalog = catalog_with_entry_points()

    assert "acme.bad" not in catalog.list_transforms()


def test_catalog_entry_points_skip_wrong_generator_kind() -> None:
    bad = mock.Mock()
    bad.name = "acme.bad"
    bad.value = "pkg:Bad"
    bad.load.return_value = lambda: object()

    def _entry_points(group: str):
        return [bad] if group == "ton.generators" else []

    with mock.patch("ton._registry.entry_points", side_effect=_entry_points):
        catalog = catalog_with_entry_points()

    assert "acme.bad" not in catalog.list_data_types()


def test_catalog_entry_point_without_namespace_uses_plugin_namespace() -> None:
    class CustomTransform(BaseTransform):
        type_name: ClassVar[str] = "trim"

    ep = mock.Mock()
    ep.name = "trim"
    ep.value = "pkg:Transform"
    ep.load.return_value = CustomTransform

    def _entry_points(group: str):
        return [ep] if group == "ton.transforms" else []

    with mock.patch("ton._registry.entry_points", side_effect=_entry_points):
        catalog = catalog_with_entry_points()

    assert "plugin.trim" in catalog.list_transforms()

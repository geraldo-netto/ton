"""Tests for the auto-discovering registry."""

from __future__ import annotations

import inspect
import subprocess
import sys
import threading
from random import Random
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest import mock

import pytest

from ton._registry import (
    ENTRY_POINT_GROUP,
    EntryPointSelector,
    ExtensionCatalog,
    RegistryError,
    build_extension_catalog,
    catalog_with_entry_points,
    clear_default_registry_cache,
    default_registry,
    discover_generator_classes,
    normalize_reference,
    registry_with_entry_points,
    resolve_reference,
    runtime_type_name,
)
from ton._transforms import BaseTransform
from ton._validation import NonEmptyValidator
from ton.generators import Generator, StringGenerator


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


def test_resolve_reference_handles_bare_and_core_qualified_catalogs() -> None:
    value = object()

    assert resolve_reference({"string": value}, "core.string") is value
    assert resolve_reference({"core.string": value}, "string") is value
    assert runtime_type_name("core.string") == "string"
    assert runtime_type_name("string") == "string"
    assert runtime_type_name(42) == "42"


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


def test_default_registry_ignores_colliding_subclass() -> None:
    class CollidingString(StringGenerator):
        type_name = "string"

    assert CollidingString not in discover_generator_classes()
    clear_default_registry_cache()
    assert type(default_registry()["string"]) is StringGenerator


def test_clear_cache_rebuilds_defaults() -> None:
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
    allowed.dist = SimpleNamespace(name="trusted-pkg", version="1")
    skipped = mock.Mock()
    skipped.name = "skipped"
    skipped.value = "pkg:Skipped"
    skipped.dist = SimpleNamespace(name="trusted-pkg", version="1")

    with mock.patch("ton._registry.entry_points", return_value=[allowed, skipped]):
        registry = registry_with_entry_points(
            allowed_selectors={EntryPointSelector(ENTRY_POINT_GROUP, "trusted-pkg", "allowed")}
        )

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
    catalog.register_validator("plugin", "custom", NonEmptyValidator())

    assert "string" in catalog.list_data_types()
    assert "core.string" in catalog.list_data_types()
    assert "plugin.custom" in catalog.list_data_types()
    assert "plugin.trim" in catalog.list_transforms()
    assert "plugin.custom" in catalog.list_validators()
    assert catalog.get_data_type("plugin.custom").generate({}, Random(0)) == "custom"
    assert catalog.get_transform("plugin.trim").type_name == "trim"


def test_catalog_returns_isolated_flattened_views_until_registration() -> None:
    class CustomGenerator(Generator):
        type_name = "widget"

        def generate(self, prepared: Any, rng: Random) -> str:
            del prepared, rng
            return "w"

    catalog = build_extension_catalog()
    first = catalog.generators()
    first.clear()
    assert "string" in catalog.generators()

    catalog.register_data_type("acme", "widget", CustomGenerator())

    assert "acme.widget" in catalog.generators()


def test_catalog_returns_fresh_generator_instances_per_registry() -> None:
    catalog = build_extension_catalog()

    first = catalog.generators()
    second = catalog.generators()

    assert first["sequence"] is first["core.sequence"]
    assert first["sequence"] is not second["sequence"]


def test_catalog_returns_fresh_transform_and_validator_instances() -> None:
    catalog = build_extension_catalog()
    first_transforms, second_transforms = catalog.transforms(), catalog.transforms()
    first_validators, second_validators = catalog.validators(), catalog.validators()

    assert first_transforms["identity"] is first_transforms["core.identity"]
    assert first_transforms["identity"] is not second_transforms["identity"]
    assert first_validators["non_empty"] is first_validators["core.non_empty"]
    assert first_validators["non_empty"] is not second_validators["non_empty"]


def test_catalog_serializes_registration_and_snapshot_reads() -> None:
    catalog = build_extension_catalog()
    started = threading.Event()
    completed = threading.Event()

    def register() -> None:
        started.set()
        catalog.register_validator("plugin", "check", NonEmptyValidator())
        completed.set()

    with catalog._lock:
        thread = threading.Thread(target=register)
        thread.start()
        assert started.wait(timeout=1)
        assert not completed.wait(timeout=0.05)
    thread.join(timeout=1)

    assert completed.is_set()
    assert "plugin.check" in catalog.validators()


def test_extension_catalog_rejects_builtin_replacement() -> None:
    catalog = build_extension_catalog()

    with pytest.raises(RegistryError, match="reserved"):
        catalog.register_data_type("core", "string", default_registry()["string"])


def test_extension_catalog_rejects_new_core_registration() -> None:
    class CustomGenerator(Generator):
        type_name = "custom_core"

        def generate(self, prepared: Any, rng: Random) -> str:
            return "custom"

    catalog = ExtensionCatalog(generators={})

    with pytest.raises(RegistryError, match="reserved"):
        catalog.register_data_type("core", "custom_core", CustomGenerator())


def test_extension_catalog_rejects_invalid_validator() -> None:
    with pytest.raises(TypeError, match="Validator protocol"):
        build_extension_catalog().register_validator("plugin", "bad", object())


def test_extension_catalog_rejects_invalid_generator_and_transform() -> None:
    catalog = build_extension_catalog()

    with pytest.raises(TypeError, match="Generator"):
        catalog.register_data_type("plugin", "bad", object())
    with pytest.raises(TypeError, match="Transform protocol"):
        catalog.register_transform("plugin", "bad", object())


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
    validator_ep.load.return_value = NonEmptyValidator

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
    allowed.dist = SimpleNamespace(name="acme-plugins", version="1")
    skipped = mock.Mock()
    skipped.name = "acme.skip"
    skipped.value = "pkg:Skip"
    skipped.dist = SimpleNamespace(name="acme-plugins", version="1")

    def _entry_points(group: str):
        return [allowed, skipped] if group == "ton.transforms" else []

    with mock.patch("ton._registry.entry_points", side_effect=_entry_points):
        catalog = catalog_with_entry_points(
            allowed_selectors={EntryPointSelector("ton.transforms", "acme-plugins", "acme.trim")}
        )

    assert "acme.trim" in catalog.list_transforms()
    skipped.load.assert_not_called()


def test_entry_point_selector_binds_group_distribution_and_name() -> None:
    class CustomGenerator(Generator):
        type_name = "custom"

        def generate(self, prepared: Any, rng: Random) -> str:
            del prepared, rng
            return "trusted"

    trusted = mock.Mock()
    trusted.name = "acme.custom"
    trusted.value = "trusted_pkg:Generator"
    trusted.dist = SimpleNamespace(name="Trusted_Pkg", version="1")
    trusted.load.return_value = CustomGenerator
    impersonator = mock.Mock()
    impersonator.name = "acme.custom"
    impersonator.value = "evil_pkg:Generator"
    impersonator.dist = SimpleNamespace(name="evil-pkg", version="1")
    wrong_group = mock.Mock()
    wrong_group.name = "acme.custom"
    wrong_group.value = "trusted_pkg:Validator"
    wrong_group.dist = SimpleNamespace(name="trusted-pkg", version="1")
    unidentified = mock.Mock()
    unidentified.name = "acme.custom"
    unidentified.value = "unknown_pkg:Generator"
    unidentified.dist = None
    invalid_distribution = mock.Mock()
    invalid_distribution.name = "acme.custom"
    invalid_distribution.value = "invalid_pkg:Generator"
    invalid_distribution.dist = SimpleNamespace(name="invalid/name", version="1")

    def _entry_points(group: str) -> list[Any]:
        if group == "ton.generators":
            return [impersonator, trusted, unidentified, invalid_distribution]
        if group == "ton.validators":
            return [wrong_group]
        return []

    selector = EntryPointSelector.parse("ton.generators:trusted-pkg:acme.custom")
    with mock.patch("ton._registry.entry_points", side_effect=_entry_points):
        catalog = catalog_with_entry_points(allowed_selectors={selector})

    assert catalog.get_data_type("acme.custom").generate({}, Random(0)) == "trusted"
    impersonator.load.assert_not_called()
    wrong_group.load.assert_not_called()
    unidentified.load.assert_not_called()
    invalid_distribution.load.assert_not_called()


def test_catalog_rejects_duplicate_providers_before_loading() -> None:
    first = mock.Mock()
    first.name = "acme.custom"
    first.value = "first_pkg:Generator"
    first.dist = SimpleNamespace(name="first-pkg", version="1")
    second = mock.Mock()
    second.name = "acme.custom"
    second.value = "second_pkg:Generator"
    second.dist = SimpleNamespace(name="second-pkg", version="1")

    def _entry_points(group: str) -> list[Any]:
        return [second, first] if group == "ton.generators" else []

    with mock.patch("ton._registry.entry_points", side_effect=_entry_points):
        catalog = catalog_with_entry_points()

    assert "acme.custom" not in catalog.list_data_types()
    first.load.assert_not_called()
    second.load.assert_not_called()


def test_entry_point_selector_rejects_name_only_and_unknown_group() -> None:
    selector = EntryPointSelector.parse("ton.generators:Trusted_Pkg:custom")
    assert selector.distribution == "trusted-pkg"
    assert str(selector) == "ton.generators:trusted-pkg:custom"

    with pytest.raises(RegistryError, match="GROUP:DISTRIBUTION:NAME"):
        EntryPointSelector.parse("custom")
    with pytest.raises(RegistryError, match="unsupported entry-point group"):
        EntryPointSelector.parse("unknown:acme:custom")
    with pytest.raises(RegistryError, match="entry-point name"):
        EntryPointSelector.parse("ton.generators:acme:")
    with pytest.raises(RegistryError, match="invalid distribution"):
        EntryPointSelector.parse("ton.generators:invalid/name:custom")


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


def test_catalog_entry_points_require_complete_transform_protocol() -> None:
    class IncompleteTransform:
        def prepare(self, spec):
            return spec

        def apply(self, prepared, value, rng):
            return value

        def prove(self, prepared, before, after):
            return True

    bad = mock.Mock()
    bad.name = "acme.incomplete"
    bad.value = "pkg:IncompleteTransform"
    bad.load.return_value = IncompleteTransform

    def _entry_points(group: str):
        return [bad] if group == "ton.transforms" else []

    with mock.patch("ton._registry.entry_points", side_effect=_entry_points):
        catalog = catalog_with_entry_points()

    assert "acme.incomplete" not in catalog.list_transforms()


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


def test_catalog_entry_point_metadata_failure_is_transactional() -> None:
    class ReadOnlyGenerator(Generator):
        type_name = "readonly"

        def __setattr__(self, name: str, value: Any) -> None:
            if name.startswith("_ton_plugin_"):
                raise AttributeError("read-only metadata")
            super().__setattr__(name, value)

        def generate(self, prepared: Any, rng: Random) -> str:
            del prepared, rng
            return "value"

    ep = mock.Mock()
    ep.name = "acme.readonly"
    ep.value = "pkg:ReadOnlyGenerator"
    ep.load.return_value = ReadOnlyGenerator

    def _entry_points(group: str):
        return [ep] if group == "ton.generators" else []

    with mock.patch("ton._registry.entry_points", side_effect=_entry_points):
        catalog = catalog_with_entry_points()

    assert "acme.readonly" not in catalog.list_data_types()


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

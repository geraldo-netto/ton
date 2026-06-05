"""Tests for the auto-discovering registry."""

from __future__ import annotations

import inspect
from random import Random
from typing import Any
from unittest import mock

from ton._registry import (
    clear_default_registry_cache,
    default_registry,
    discover_generator_classes,
    registry_with_entry_points,
)
from ton.generators import Generator

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
    skipped.load.assert_not_called()


def test_registry_skips_entry_point_that_returns_non_generator() -> None:
    bad = mock.Mock()
    bad.name = "bad"
    bad.value = "pkg:Bad"
    bad.load.return_value = lambda: object()

    with mock.patch("ton._registry.entry_points", return_value=[bad]):
        registry = registry_with_entry_points()

    assert "bad" not in registry

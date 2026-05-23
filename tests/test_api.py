"""Tests for the public ton.api facade."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from random import Random
from typing import Any

import pytest

from ton import api
from ton.generators import Generator


def test_generate_yields_iterator(basic_config: dict) -> None:
    rows = list(api.generate(basic_config, seed=0))
    assert len(rows) == 4
    assert all(row.isdigit() for row in rows)


def test_generate_is_seed_deterministic(basic_config: dict) -> None:
    first = list(api.generate(basic_config, seed=42))
    second = list(api.generate(basic_config, seed=42))
    assert first == second


def test_generate_from_file_round_trip(write_config) -> None:
    path = write_config()
    rows = list(api.generate_from_file(str(path), seed=7))
    assert len(rows) == 4


def test_build_registry_includes_builtins() -> None:
    registry = api.build_registry(include_entry_points=False)
    assert "integer" in registry
    assert "date" in registry
    assert "lmhash" in registry


def test_custom_registry_can_override_or_add_types() -> None:
    class TagGenerator(Generator):
        type_name = "tag"

        def generate(self, spec: Mapping[str, Any], rng: Random) -> str:
            return spec["tag"]

    registry = api.build_registry(include_entry_points=False)
    registry["tag"] = TagGenerator()
    config = {
        "rows": 3,
        "format": "[$t$]",
        "types": {"t": {"type": "tag", "tag": "hello"}},
    }
    rows = list(api.generate(config, registry=registry, seed=0))
    assert rows == ["[hello]", "[hello]", "[hello]"]


def test_load_config_validates(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    from ton.api import ConfigError

    with pytest.raises(ConfigError):
        api.load_config(str(bad))

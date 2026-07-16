"""Tests for the public ton.api facade."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from random import Random
from typing import Any
from unittest import mock

import pytest

from ton import api
from ton.generators import Generator


def test_generate_yields_iterator(basic_config: dict) -> None:
    rows = list(api.generate(basic_config, seed=0))
    assert len(rows) == 4
    assert all(row.isdigit() for row in rows)


def test_engine_options_is_public_parameter_object() -> None:
    options = api.EngineOptions(seed=42, proof_mode="audit")

    assert options.seed == 42
    assert options.proof_mode == "audit"


def test_generate_is_seed_deterministic(basic_config: dict) -> None:
    first = list(api.generate(basic_config, seed=42))
    second = list(api.generate(basic_config, seed=42))
    assert first == second


def test_generate_from_file_round_trip(write_config) -> None:
    path = write_config()
    rows = list(api.generate_from_file(str(path), seed=7))
    assert len(rows) == 4


def test_build_registry_includes_builtins() -> None:
    with pytest.warns(DeprecationWarning):
        registry = api.build_registry(include_entry_points=False)
    assert "integer" in registry
    assert "date" in registry
    assert "lmhash" in registry


def test_build_registry_warns_pointing_at_catalog() -> None:
    with pytest.warns(DeprecationWarning, match="build_extension_catalog"):
        api.build_registry()


def test_build_registry_can_opt_into_entry_points(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def _fake_registry(*, allowed_names=None):
        seen["allowed_names"] = allowed_names
        return {}

    monkeypatch.setattr(api, "registry_with_entry_points", _fake_registry)
    with pytest.warns(DeprecationWarning):
        registry = api.build_registry(
            include_entry_points=True,
            allowed_entry_points={"custom"},
        )
    assert registry == {}
    assert seen["allowed_names"] == {"custom"}


def test_custom_registry_can_override_or_add_types() -> None:
    class TagGenerator(Generator):
        type_name = "tag"

        def generate(self, prepared: Any, rng: Random) -> str:
            return prepared["tag"]

    with pytest.warns(DeprecationWarning):
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


def test_public_output_sink_replaces_atomically_and_preserves_mode(tmp_path: Path) -> None:
    output = tmp_path / "rows.txt"
    output.write_text("old\n", encoding="utf-8")
    os.chmod(output, 0o640)

    with api.open_output_path(str(output)) as stream:
        stream.write("new\n")

    assert output.read_text(encoding="utf-8") == "new\n"
    assert stat.S_IMODE(output.stat().st_mode) == 0o640


def test_public_output_sink_rolls_back_failed_write(tmp_path: Path) -> None:
    output = tmp_path / "rows.txt"
    output.write_text("old\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="failed"), api.open_output_path(str(output)) as stream:
        stream.write("partial\n")
        raise RuntimeError("failed")

    assert output.read_text(encoding="utf-8") == "old\n"
    assert list(tmp_path.glob(".rows.txt.*.tmp")) == []


def test_public_output_sink_no_clobber_publish_is_atomic(tmp_path: Path) -> None:
    output = tmp_path / "rows.txt"

    with (
        pytest.raises(FileExistsError),
        api.open_output_path(str(output), no_clobber=True) as stream,
    ):
        stream.write("generated\n")
        output.write_text("racing writer\n", encoding="utf-8")

    assert output.read_text(encoding="utf-8") == "racing writer\n"
    assert list(tmp_path.glob(".rows.txt.*.tmp")) == []


def test_public_output_sink_no_clobber_publishes_new_file(tmp_path: Path) -> None:
    output = tmp_path / "rows.txt"

    with api.open_output_path(str(output), no_clobber=True) as stream:
        stream.write("generated\n")

    assert output.read_text(encoding="utf-8") == "generated\n"


def test_atomic_output_fsyncs_parent_directory(tmp_path: Path) -> None:
    output = tmp_path / "rows.txt"

    with (
        mock.patch("ton._output._fsync_directory") as fsync_directory,
        api.open_output_path(str(output)) as stream,
    ):
        stream.write("row\n")

    fsync_directory.assert_called_once_with(str(tmp_path))


def test_directory_fsync_is_noop_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    from ton import _output

    monkeypatch.setattr(_output.os, "name", "nt")
    with mock.patch.object(_output.os, "open") as open_directory:
        _output._fsync_directory(".")

    open_directory.assert_not_called()


def test_public_output_sink_matches_cli_symlink_policy(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("old\n", encoding="utf-8")
    link = tmp_path / "rows.txt"
    link.symlink_to(target)

    with pytest.raises(OSError, match="symbolic-link"), api.open_output_path(str(link)):
        pass

    assert link.is_symlink()
    assert target.read_text(encoding="utf-8") == "old\n"


def test_output_encoding_error_carries_codec_and_field_context() -> None:
    error = api.OutputEncodingError("ascii", "ordinal not in range", field_name="city")

    assert error.encoding == "ascii"
    assert error.field_name == "city"
    assert "field 'city'" in str(error)


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"rows": True, "format": "$x$", "types": {"x": {"type": "string", "values": ["x"]}}},
        {"rows": 1, "format": 123, "types": {"x": {"type": "string", "values": ["x"]}}},
    ],
)
def test_in_memory_generation_uses_structural_validation(config: dict) -> None:
    with pytest.raises(api.ConfigError):
        list(api.generate(config))

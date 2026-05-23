"""Unit tests for the config loader/validator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ton._config import MAX_ROWS, ConfigError, load
from ton._engine import Engine, TemplateError


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _valid_payload() -> dict:
    return {
        "rows": 3,
        "format": "$a$",
        "types": {"a": {"type": "string", "values": ["x"]}},
    }


def test_load_returns_parsed_dict(tmp_path: Path) -> None:
    path = _write(tmp_path, _valid_payload())
    config = load(path)
    assert config["rows"] == 3
    assert config["format"] == "$a$"


def test_missing_file_raises_filenotfound(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load(tmp_path / "nope.json")


@pytest.mark.parametrize(
    "mutator",
    [
        lambda p: p.pop("rows"),
        lambda p: p.pop("format"),
        lambda p: p.pop("types"),
    ],
)
def test_missing_required_keys_raise(tmp_path: Path, mutator) -> None:
    payload = _valid_payload()
    mutator(payload)
    path = _write(tmp_path, payload)
    with pytest.raises(ConfigError):
        load(path)


def test_negative_rows_rejected(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["rows"] = -1
    path = _write(tmp_path, payload)
    with pytest.raises(ConfigError):
        load(path)


def test_type_spec_missing_type_field_rejected(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["types"]["a"] = {"values": ["x"]}
    path = _write(tmp_path, payload)
    with pytest.raises(ConfigError):
        load(path)


def test_rows_above_max_rejected(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["rows"] = MAX_ROWS + 1
    path = _write(tmp_path, payload)
    with pytest.raises(ConfigError, match="MAX_ROWS"):
        load(path)


def test_bad_per_spec_values_caught_at_engine_construction(tmp_path: Path) -> None:
    """Per-type validation moved to Generator.prepare (REL-011): config.load
    succeeds on structurally-valid JSON, Engine() raises TemplateError on
    bad spec fields."""
    payload = _valid_payload()
    payload["types"]["a"] = {"type": "string", "values": []}
    path = _write(tmp_path, payload)
    config = load(path)  # structural validation passes
    with pytest.raises(TemplateError):
        Engine(config)


def test_template_references_undeclared_variable_rejected(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["format"] = "$missing$"
    path = _write(tmp_path, payload)
    with pytest.raises(ConfigError, match="undeclared variable"):
        load(path)


def test_bool_rows_rejected(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["rows"] = True  # JSON 'true' should not slip past int-check.
    path = _write(tmp_path, payload)
    with pytest.raises(ConfigError):
        load(path)

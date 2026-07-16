"""Unit tests for the config loader/validator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import pytest

from ton import api
from ton._config import MAX_ROWS, ConfigError, load
from ton._engine import Engine, TemplateError
from ton._transforms import BaseTransform, TransformCapabilities


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


def test_namespaced_core_type_is_accepted_by_engine(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["types"]["a"] = {"type": "core.string", "values": ["x"]}
    path = _write(tmp_path, payload)

    assert list(Engine(load(path))) == ["x", "x", "x"]


def test_transform_chain_shape_is_accepted(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["types"]["a"]["transforms"] = [{"type": "core.identity"}]
    path = _write(tmp_path, payload)

    assert load(path)["types"]["a"]["transforms"][0]["type"] == "core.identity"


def test_transform_chain_must_be_a_list(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["types"]["a"]["transforms"] = {"type": "core.identity"}
    path = _write(tmp_path, payload)

    with pytest.raises(ConfigError, match="transforms"):
        load(path)


def test_transform_entries_need_type(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["types"]["a"]["transforms"] = [{}]
    path = _write(tmp_path, payload)

    with pytest.raises(ConfigError, match="transform 0"):
        load(path)


def test_type_field_must_be_a_string(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["types"]["a"]["type"] = 123
    path = _write(tmp_path, payload)

    with pytest.raises(ConfigError, match="non-empty string"):
        load(path)


def test_validate_config_lists_available_types_for_unknown_type() -> None:
    payload = _valid_payload()
    payload["types"]["a"] = {"type": "missing"}

    with pytest.raises(ConfigError, match="Available types:"):
        api.validate_config(payload)


def test_encoding_accepts_known_codec() -> None:
    payload = _valid_payload()
    payload["encoding"] = "latin-1"
    api.validate_config(payload)
    assert api.output_encoding(payload) == "latin-1"


def test_encoding_defaults_to_utf8() -> None:
    assert api.output_encoding(_valid_payload()) == "utf-8"


def test_encoding_rejects_unknown_codec(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["encoding"] = "not-a-codec"
    with pytest.raises(ConfigError, match="not a known codec"):
        api.load_config(str(_write(tmp_path, payload)))


@pytest.mark.parametrize("encoding", ["base64", "hex", "rot13"])
def test_encoding_rejects_non_text_codec(tmp_path: Path, encoding: str) -> None:
    payload = _valid_payload()
    payload["encoding"] = encoding
    with pytest.raises(ConfigError, match="text codec"):
        api.load_config(str(_write(tmp_path, payload)))


def test_encoding_rejects_non_string(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["encoding"] = 42
    with pytest.raises(ConfigError, match="'encoding' must be a string"):
        api.load_config(str(_write(tmp_path, payload)))


def test_validate_config_prepares_composite_field() -> None:
    # Exercises the composite prepare path in per-field validation (CLI-001):
    # a valid oneOf passes, and a bad nested spec is rejected here.
    payload = _valid_payload()
    payload["types"]["a"] = {
        "type": "oneOf",
        "choices": [
            {"type": "string", "values": ["x"]},
            {"type": "integer", "minValue": 0, "maxValue": 9},
        ],
    }
    api.validate_config(payload)

    payload["types"]["a"]["choices"][1] = {"type": "integer", "minValue": 9, "maxValue": 0}
    with pytest.raises(ConfigError, match="Invalid spec"):
        api.validate_config(payload)


def test_validate_config_reports_unknown_namespace() -> None:
    payload = _valid_payload()
    payload["types"]["a"] = {"type": "other.string"}

    with pytest.raises(ConfigError, match="Unknown namespace 'other'"):
        api.validate_config(payload)


def test_validate_config_wraps_bad_reference() -> None:
    payload = _valid_payload()
    payload["types"]["a"] = {"type": "bad-name"}

    with pytest.raises(ConfigError, match="letters, numbers"):
        api.validate_config(payload)


def test_validate_config_lists_available_transforms() -> None:
    payload = _valid_payload()
    payload["types"]["a"]["transforms"] = [{"type": "missing"}]

    with pytest.raises(ConfigError, match="Available transforms:"):
        api.validate_config(payload)


def test_validate_config_rejects_incompatible_transform_chain() -> None:
    class UnpairedOnlyTransform(BaseTransform):
        type_name: ClassVar[str] = "unpaired"
        capabilities: ClassVar[TransformCapabilities] = TransformCapabilities(accepts_paired=False)

    payload = {
        "rows": 1,
        "format": "$word$;$word[id]$",
        "types": {
            "word": {
                "type": "lmhash",
                "values": ["secret"],
                "transforms": [{"type": "plugin.unpaired"}],
            }
        },
    }
    catalog = api.build_extension_catalog()
    catalog.register_transform("plugin", "unpaired", UnpairedOnlyTransform())

    with pytest.raises(ConfigError, match="does not accept paired input"):
        api.validate_config(payload, catalog=catalog)


def test_config_and_engine_agree_on_paired_transform_chains() -> None:
    class PreservePair(BaseTransform):
        type_name: ClassVar[str] = "preserve"
        capabilities: ClassVar[TransformCapabilities] = TransformCapabilities(True, True)

    class DropPair(BaseTransform):
        type_name: ClassVar[str] = "drop"
        capabilities: ClassVar[TransformCapabilities] = TransformCapabilities(True, False)

    class SingleOnly(BaseTransform):
        type_name: ClassVar[str] = "single"
        capabilities: ClassVar[TransformCapabilities] = TransformCapabilities(False, False)

    transforms = {
        "plugin.preserve": PreservePair(),
        "plugin.drop": DropPair(),
        "plugin.single": SingleOnly(),
    }
    catalog = api.build_extension_catalog()
    for reference, transform in transforms.items():
        namespace, name = reference.split(".")
        catalog.register_transform(namespace, name, transform)

    def payload(chain: list[str]) -> dict:
        return {
            "rows": 1,
            "format": "$word$",
            "types": {
                "word": {
                    "type": "lmhash",
                    "values": ["secret"],
                    "transforms": [{"type": reference} for reference in chain],
                }
            },
        }

    accepted = payload(["plugin.preserve", "plugin.drop", "plugin.single"])
    api.validate_config(accepted, catalog=catalog)
    Engine(accepted, transforms=transforms)

    rejected = payload(["plugin.preserve", "plugin.single"])
    with pytest.raises(ConfigError, match="does not accept paired input"):
        api.validate_config(rejected, catalog=catalog)
    with pytest.raises(TemplateError, match="does not accept paired input"):
        Engine(rejected, transforms=transforms)


def test_validate_config_accepts_core_identity_transform() -> None:
    payload = _valid_payload()
    payload["types"]["a"]["transforms"] = [{"type": "identity"}]

    api.validate_config(payload)


def test_unknown_key_policy_defines_root_and_common_field_keys() -> None:
    from ton._config import COMMON_FIELD_KEYS, ROOT_KEYS, _unknown_key_message

    assert {"rows", "format", "types", "encoding"} == ROOT_KEYS
    assert {"type", "transforms", "validators"} == COMMON_FIELD_KEYS
    assert "Did you mean 'rows'?" in _unknown_key_message("config", "row", ROOT_KEYS)


@pytest.mark.parametrize("reference", [123, ""])
def test_transform_type_must_be_non_empty_string(reference: object) -> None:
    payload = _valid_payload()
    payload["types"]["a"]["transforms"] = [{"type": reference}]

    with pytest.raises(ConfigError, match="transform 0 'type' must be a non-empty string"):
        api.validate_config(payload)

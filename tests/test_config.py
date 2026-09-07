"""Unit tests for the config loader/validator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import pytest

from ton import api
from ton._config import ConfigError, load
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


def test_non_utf8_config_raises_config_error(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_bytes(b"\xff")

    with pytest.raises(ConfigError, match="valid UTF-8"):
        load(path)


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


def test_rows_accept_arbitrary_non_negative_integers(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["rows"] = 10**100
    path = _write(tmp_path, payload)

    assert load(path)["rows"] == 10**100


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

    with pytest.raises(ConfigError, match="Unknown type 'missing'"):
        api.validate_config(payload)


def test_validate_config_prepares_unused_fields() -> None:
    payload = _valid_payload()
    payload["types"]["unused"] = {"type": "integer", "minValue": 2, "maxValue": 1}

    with pytest.raises(ConfigError, match="unused.*maxValue.*must be >=.*minValue"):
        api.validate_config(payload)

    payload["types"]["unused"] = {"type": "missing"}
    with pytest.raises(ConfigError, match="Unknown type 'missing'.*unused"):
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
    config_path = str(_write(tmp_path, payload))
    with pytest.raises(ConfigError, match="not a known codec"):
        api.load_config(config_path)


@pytest.mark.parametrize("encoding", ["base64", "hex", "rot13"])
def test_encoding_rejects_non_text_codec(tmp_path: Path, encoding: str) -> None:
    payload = _valid_payload()
    payload["encoding"] = encoding
    config_path = str(_write(tmp_path, payload))
    with pytest.raises(ConfigError, match="text codec"):
        api.load_config(config_path)


def test_encoding_rejects_non_string(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["encoding"] = 42
    config_path = str(_write(tmp_path, payload))
    with pytest.raises(ConfigError, match="'encoding' must be a string"):
        api.load_config(config_path)


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

    with pytest.raises(ConfigError, match="Unknown type 'other.string'"):
        api.validate_config(payload)


def test_validate_config_wraps_bad_reference() -> None:
    payload = _valid_payload()
    payload["types"]["a"] = {"type": "bad-name"}

    with pytest.raises(ConfigError, match="letters, numbers"):
        api.validate_config(payload)


def test_validate_config_lists_available_transforms() -> None:
    payload = _valid_payload()
    payload["types"]["a"]["transforms"] = [{"type": "missing"}]

    with pytest.raises(
        ConfigError,
        match="Unknown transform 'missing'.*Available transforms:.*identity.*namespace.name",
    ):
        api.validate_config(payload)


def test_validate_config_rejects_transform_owned_key_typo() -> None:
    payload = _valid_payload()
    payload["types"]["a"]["transforms"] = [{"type": "identity", "extra": True}]

    with pytest.raises(ConfigError, match=r"transforms\[0\].extra"):
        api.validate_config(payload)


def test_source_independent_transform_must_be_first() -> None:
    payload = _valid_payload()
    payload["types"]["a"]["transforms"] = [
        {"type": "identity"},
        {
            "type": "distribution",
            "choices": [
                {"spec": {"type": "string", "values": ["a"]}},
                {"spec": {"type": "string", "values": ["b"]}},
            ],
        },
    ]

    with pytest.raises(ConfigError, match="Source-independent transform.*must be the first"):
        api.validate_config(payload)


def test_validate_config_lists_available_validators() -> None:
    payload = _valid_payload()
    payload["types"]["a"]["validators"] = ["missing"]

    with pytest.raises(
        ConfigError,
        match="Unknown validator 'missing'.*Available validators:.*non_empty.*namespace.name",
    ):
        api.validate_config(payload)


def test_config_validated_event_lists_every_extension_kind(caplog) -> None:
    payload = _valid_payload()

    with caplog.at_level("INFO", logger="ton"):
        api.validate_config(payload)

    record = next(record for record in caplog.records if record.event == "config_validated")
    assert "string" in record.available_types
    assert "identity" in record.available_transforms
    assert "non_empty" in record.available_validators


def test_validate_config_rejects_incompatible_transform_chain() -> None:
    class UnpairedOnlyTransform(BaseTransform):
        type_name: ClassVar[str] = "unpaired"
        capabilities: ClassVar[TransformCapabilities] = TransformCapabilities(accepts_paired=False)

    payload = {
        "rows": 1,
        "format": "$word$;$word[id]$",
        "types": {
            "word": {
                "type": "hash",
                "algorithm": "ntlm",
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
                    "type": "hash",
                    "algorithm": "ntlm",
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

    actual_root_keys = ROOT_KEYS
    actual_common_keys = COMMON_FIELD_KEYS
    expected_root_keys = {"rows", "format", "types", "encoding", "maxRowWidth"}
    expected_common_keys = {"type", "transforms", "validators"}
    assert actual_root_keys == expected_root_keys
    assert actual_common_keys == expected_common_keys
    assert "Did you mean 'rows'?" in _unknown_key_message("config", "row", ROOT_KEYS)


def test_max_row_width_must_be_positive() -> None:
    payload = _valid_payload()
    payload["maxRowWidth"] = 0
    with pytest.raises(ConfigError, match="positive integer"):
        api.validate_config(payload)


@pytest.mark.parametrize("reference", [123, ""])
def test_transform_type_must_be_non_empty_string(reference: object) -> None:
    payload = _valid_payload()
    payload["types"]["a"]["transforms"] = [{"type": reference}]

    with pytest.raises(ConfigError, match="transform 0 'type' must be a non-empty string"):
        api.validate_config(payload)


def test_unknown_root_key_is_rejected_with_suggestion() -> None:
    payload = _valid_payload()
    payload["row"] = payload["rows"]

    with pytest.raises(ConfigError, match="config.row.*Did you mean 'rows'"):
        api.validate_config(payload)


def test_common_field_key_typo_is_rejected() -> None:
    payload = _valid_payload()
    payload["types"]["a"]["transform"] = []

    with pytest.raises(ConfigError, match="types.a.transform.*Did you mean 'transforms'"):
        api.validate_config(payload)


def test_builtin_generator_rejects_unknown_owned_key() -> None:
    payload = _valid_payload()
    payload["types"]["a"]["value"] = ["x"]

    with pytest.raises(ConfigError, match="types.a.value.*Did you mean 'values'"):
        api.validate_config(payload)


def test_validate_config_rejects_weighted_choice_wrapper_typo() -> None:
    payload = {
        "rows": 1,
        "format": "$value$",
        "types": {
            "value": {
                "type": "weighted",
                "choices": [
                    {
                        "weigth": 2,
                        "spec": {"type": "string", "values": ["x"]},
                    }
                ],
            }
        },
    }

    with pytest.raises(
        ConfigError,
        match=r"weighted\.choices\[0\]\.weigth.*Did you mean 'weight'",
    ):
        api.validate_config(payload)


def test_plugin_generator_may_own_custom_keys() -> None:
    from random import Random
    from typing import Any

    from ton.generators import Generator

    class PluginGenerator(Generator):
        type_name = "plugin"

        def generate(self, prepared: Any, rng: Random) -> str:
            return str(prepared["custom"])

    payload = {"rows": 1, "format": "$a$", "types": {"a": {"type": "plugin.x", "custom": 1}}}
    catalog = api.build_extension_catalog()
    catalog.register_data_type("plugin", "x", PluginGenerator())

    api.validate_config(payload, catalog=catalog)


def test_plugin_metadata_type_key_is_not_a_nested_generator() -> None:
    from random import Random
    from typing import Any

    from ton.generators import Generator

    class PluginGenerator(Generator):
        type_name = "metadata"

        def generate(self, prepared: Any, rng: Random) -> str:
            del rng
            return str(prepared["metadata"]["custom"])

    payload = {
        "rows": 1,
        "format": "$a$",
        "types": {
            "a": {
                "type": "plugin.metadata",
                "metadata": {"type": "string", "custom": 1},
            }
        },
    }
    catalog = api.build_extension_catalog()
    catalog.register_data_type("plugin", "metadata", PluginGenerator())

    api.validate_config(payload, catalog=catalog)


def test_nested_builtin_generator_rejects_key_typo() -> None:
    payload = {
        "rows": 1,
        "format": "$a$",
        "types": {
            "a": {
                "type": "sequence_of",
                "count": 1,
                "spec": {"type": "string", "value": ["x"]},
            }
        },
    }

    with pytest.raises(ConfigError, match=r"types.a.spec.value.*Did you mean 'values'"):
        api.validate_config(payload)


def test_transform_owned_child_specs_reach_the_key_boundary() -> None:
    """A typo inside a distribution candidate is rejected with its path (CFG-004)."""
    config = {
        "rows": 1,
        "format": "$x$",
        "types": {
            "x": {
                "type": "string",
                "values": ["s"],
                "transforms": [
                    {
                        "type": "distribution",
                        "choices": [
                            {
                                "weight": 1,
                                "spec": {
                                    "type": "integer",
                                    "minValue": 1,
                                    "maxValue": 9,
                                    "padWithZer": True,
                                },
                            },
                            {"weight": 1, "spec": {"type": "string", "values": ["b"]}},
                        ],
                    }
                ],
            }
        },
    }

    with pytest.raises(ConfigError) as excinfo:
        api.validate_config(config)

    assert "types.x.transforms[0].choices[0].spec.padWithZer" in str(excinfo.value)
    assert "padWithZero" in str(excinfo.value)

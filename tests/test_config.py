"""Unit tests for the config loader/validator."""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from random import Random
from typing import Any, ClassVar

import pytest

from ton import api
from ton._config import ConfigError, load
from ton._engine import Engine, TemplateError
from ton._transforms import BaseTransform, TransformCapabilities, TransformProof
from ton.generators import Generator


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
    from ton._config import ROOT_KEYS, _unknown_key_message
    from ton._speckeys import COMMON_FIELD_KEYS

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


@pytest.mark.parametrize(
    "obsolete", [{"values": ["ignored"]}, {"weights": [0]}, {"values": ["ignored"], "weights": [0]}]
)
def test_weighted_rejects_removed_keys_in_mixed_forms(obsolete) -> None:
    """ARCH-007: only choices belongs to the weighted schema."""
    from ton import api

    field = {
        "type": "weighted",
        "choices": [{"spec": {"type": "string", "values": ["x"]}}],
        **obsolete,
    }
    config = {"rows": 1, "format": "$x$", "types": {"x": field}}
    with pytest.raises(api.ConfigError, match="Unknown key"):
        api.validate_config(config)
    with pytest.raises(api.TemplateError, match="Unknown key"):
        list(api.generate(config))


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
        match=r"types\.value\.choices\[0\]\.weigth.*Did you mean 'weight'",
    ):
        api.validate_config(payload)


@pytest.mark.parametrize("transform", [False, True])
def test_nested_choice_typo_reports_complete_owning_path(transform) -> None:
    """CFG-030: nested wrapper diagnostics identify the full configuration location."""
    import re

    distribution = {
        "type": "weighted",
        "choices": [
            {"weigth": 2, "spec": {"type": "string", "values": ["x"]}},
            {"spec": {"type": "string", "values": ["y"]}},
        ],
    }
    child = distribution
    suffix = "choices[0].weigth"
    if transform:
        distribution["type"] = "distribution"
        child = {"type": "string", "values": ["x"], "transforms": [distribution]}
        suffix = "transforms[0]." + suffix
    config = {
        "rows": 1,
        "format": "$outer$",
        "types": {
            "outer": {"type": "oneOf", "choices": [child]},
        },
    }
    with pytest.raises(
        ConfigError, match=re.escape("types.outer.choices[0]." + suffix) + ".*Did you mean 'weight'"
    ):
        api.validate_config(config)


def test_plugin_generator_may_own_custom_keys() -> None:

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


def test_config_loads_arbitrarily_large_integers(tmp_path: Path) -> None:
    """The stdlib parser's digit ceiling is not a row-count ceiling (CFG-006)."""
    big = "9" * 4301
    path = tmp_path / "big.json"
    path.write_text(
        f'{{"rows": {big}, "format": "$x$", '
        '"types": {"x": {"type": "string", "values": ["a"]}}}',
        encoding="utf-8",
    )

    assert load(path)["rows"] == int(Decimal(big))


def test_large_integer_parsing_preserves_intentional_validation_errors(tmp_path: Path) -> None:
    """Widening the parser must not swallow real config errors (CFG-006)."""
    path = tmp_path / "bad.json"
    path.write_text(
        '{"rows": -1, "format": "$x$", "types": {"x": {"type": "string", "values": ["a"]}}}',
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="non-negative integer"):
        load(path)


def test_decimal_bounds_survive_loading_exactly(tmp_path: Path) -> None:
    """Binary floats moved written bounds off the requested interval (CFG-007)."""
    path = tmp_path / "exact.json"
    path.write_text(
        '{"rows": 2, "format": "$x$", "types": {"x": {"type": "decimal", '
        '"minValue": 0.10000000000000001, "maxValue": 0.10000000000000001, '
        '"decimals": 17}}}',
        encoding="utf-8",
    )

    rows = list(api.generate(load(path), seed=1, proof_mode="all"))

    assert rows == ["0.10000000000000001"] * 2


def test_decimal_specs_serialize_exactly_into_proof_reports(tmp_path: Path) -> None:
    """Exactness must survive audit serialization too (CFG-007)."""
    import io

    from ton._proofaudit import ProofAuditWriter

    class _Reject(BaseTransform):
        type_name = "reject_exact"
        config_keys: ClassVar[frozenset[str] | None] = frozenset()

        def prove(self, prepared, before, after):  # noqa: ANN001, ANN201
            del prepared, before, after
            return TransformProof(ok=False, reason="nope")

    path = tmp_path / "spec.json"
    path.write_text(
        '{"rows": 1, "format": "$x$", "types": {"x": {"type": "decimal", '
        '"minValue": 0.5, "maxValue": 0.5, "decimals": 1, '
        '"transforms": [{"type": "reject_exact"}]}}}',
        encoding="utf-8",
    )
    engine = Engine.from_config(
        load(path), seed=1, proof_mode="audit", transforms={"reject_exact": _Reject()}
    )
    report = io.StringIO()
    engine.set_proof_failure_sink(ProofAuditWriter(report))

    list(engine)

    spec = json.loads(report.getvalue().splitlines()[0])["spec"]
    assert Decimal(spec["minValue"]) == Decimal("0.5")


def test_unknown_type_diagnostic_names_real_alternatives() -> None:
    """The narrowed registry must not report 'Available types: (none)' (CFG-008)."""
    config = {"rows": 1, "format": "$x$", "types": {"x": {"type": "nosuch"}}}

    with pytest.raises(TemplateError) as excinfo:
        list(api.generate(config))

    message = str(excinfo.value)
    assert "(none)" not in message
    for expected in ("string", "integer", "weighted"):
        assert expected in message


@pytest.mark.parametrize("restricted", [None, {}, {"only": Generator}])
def test_unknown_type_lists_exact_effective_registry(restricted) -> None:
    """CFG-008: explicit empty/restricted catalogs must not advertise built-ins."""
    config = {"rows": 1, "format": "$x$", "types": {"x": {"type": "nosuch"}}}
    with pytest.raises(TemplateError) as error:
        list(api.generate(config, registry=restricted))
    names = str(error.value).split("Available types: ")[1].removesuffix(".")
    actual = set() if names == "(none)" else set(names.split(", "))
    expected = (
        set(api.build_extension_catalog().generators()) if restricted is None else set(restricted)
    )
    assert actual == expected


def test_unknown_type_diagnostic_does_not_construct_unused_generators(monkeypatch) -> None:
    """CFG-008: available-name metadata does not require generator construction."""
    from ton.generators.string import StringGenerator

    def unexpected_init(self):
        raise AssertionError("unused string generator constructed")

    monkeypatch.setattr(StringGenerator, "__init__", unexpected_init)
    config = {"rows": 1, "format": "$x$", "types": {"x": {"type": "nosuch"}}}
    with pytest.raises(TemplateError, match="Available types"):
        list(api.generate(config))


@pytest.mark.parametrize("validate", [False, True])
def test_cli_available_types_match_the_effective_catalog(tmp_path, capsys, validate) -> None:
    """CFG-008: CLI generation and validation name the same actual references."""
    from ton.cli import main

    path = tmp_path / "unknown.json"
    path.write_text('{"rows": 1, "format": "$x$", "types": {"x": {"type": "nosuch"}}}')
    assert main([str(path), *(["--validate"] if validate else [])]) == 2
    diagnostic = capsys.readouterr().err.split("Available types: ")[1].split(".\n")[0]
    assert set(diagnostic.split(", ")) == set(api.build_extension_catalog().generators())


def test_generate_and_validate_config_agree_on_available_types() -> None:
    """Both entry points describe the same catalog for the same config (CFG-008)."""
    config = {"rows": 1, "format": "$x$", "types": {"x": {"type": "nosuch"}}}

    with pytest.raises(TemplateError) as from_generate:
        list(api.generate(config))
    with pytest.raises(ConfigError) as from_validate:
        api.validate_config(config)

    def _named(message: str) -> set[str]:
        listed = message.rsplit("Available types: ", 1)[1].rstrip(".")
        return {name.strip() for name in listed.split(",")}

    assert _named(str(from_generate.value)) == _named(str(from_validate.value))


def test_plugin_owned_keys_survive_a_resemblance_to_a_common_key() -> None:
    """Typo hints must run after ownership is resolved (CFG-005)."""

    class OptionGenerator(Generator):
        type_name = "opt"
        config_keys: ClassVar[frozenset[str] | None] = frozenset({"type", "transform"})

        def prepare(self, spec: Mapping[str, Any], context: Any = None) -> str:
            del context
            return str(spec.get("transform", "none"))

        def generate(self, prepared: str, rng: Random) -> str:
            del rng
            return prepared

    class OpenNamespaceGenerator(OptionGenerator):
        type_name = "opt_open"
        config_keys: ClassVar[frozenset[str] | None] = None

    registry = api.build_extension_catalog().generators()
    registry["opt"] = OptionGenerator()
    registry["opt_open"] = OpenNamespaceGenerator()

    for type_name in ("opt", "opt_open"):
        config = {
            "rows": 1,
            "format": "$x$",
            "types": {"x": {"type": type_name, "transform": "declared"}},
        }
        assert list(api.generate(config, seed=1, registry=registry)) == ["declared"]


def test_a_real_typo_on_a_builtin_is_still_reported_with_a_suggestion() -> None:
    config = {
        "rows": 1,
        "format": "$x$",
        "types": {"x": {"type": "string", "values": ["a"], "transform": []}},
    }

    with pytest.raises(ConfigError, match="Did you mean 'transforms'"):
        api.validate_config(config)


@pytest.mark.parametrize("entry", ["generation", "validation"])
@pytest.mark.parametrize("key", ["x", "customer"])
def test_mixed_nested_transform_errors_preserve_field_path(entry, key) -> None:
    """CFG-004: child preparation carries the actual owning path through every layer."""
    child = {
        "type": "string",
        "values": ["x"],
        "transforms": [
            {
                "type": "distribution",
                "choices": [
                    {"spec": {"type": "integer", "minvalue": 1, "maxValue": 2}},
                    {"spec": {"type": "string", "values": ["y"]}},
                ],
            }
        ],
    }
    config = {
        "rows": 1,
        "format": f"${key}$",
        "types": {key: {"type": "oneOf", "choices": [child]}},
    }
    with pytest.raises((ConfigError, TemplateError)) as error:
        if entry == "generation":
            list(api.generate(config))
        else:
            api.validate_config(config)
    assert f"types.{key}.choices[0].transforms[0].choices[0].spec.minvalue" in str(error.value)


def test_preparation_cache_cannot_alias_a_different_field_path() -> None:
    """SCALE-007: path-like field names cannot borrow another field's prepared child."""
    config = {
        "rows": 1,
        "format": "$x$:$x.choices[0]$",
        "types": {
            "x": {
                "type": "oneOf",
                "choices": [
                    {"type": "oneOf", "choices": [{"type": "string", "values": ["valid"]}]}
                ],
            },
            "x.choices[0]": {"type": "oneOf", "choices": [{}]},
        },
    }
    with pytest.raises(TemplateError, match="must be an object with a 'type' field"):
        list(api.generate(config))


@pytest.mark.parametrize("reference", ["string", "core.string"])
def test_qualified_only_registry_can_use_its_advertised_type(reference) -> None:
    """CFG-026: canonical lookup must honor qualified-only supplied registrations."""
    from ton.generators.string import StringGenerator

    config = {"rows": 2, "format": "$x$", "types": {"x": {"type": reference, "values": ["x"]}}}
    registry = {"core.string": StringGenerator()}
    assert list(api.generate(config, registry=registry, proof_mode="all")) == ["x", "x"]


def test_qualified_only_registry_prepares_deep_owned_children_iteratively() -> None:
    """CFG-026: resolving owned children must use the same catalog rules as roots."""
    import sys

    catalog = api.build_extension_catalog().generators()
    registry = {key: value for key, value in catalog.items() if key.startswith("core.")}
    spec = {"type": "core.string", "values": ["x"]}
    for _ in range(1200):
        spec = {"type": "core.oneOf", "choices": [spec]}
    config = {"rows": 1, "format": "$x$", "types": {"x": spec}}
    before = sys.getrecursionlimit()
    assert list(api.generate(config, registry=registry, proof_mode="all")) == ["x"]
    assert sys.getrecursionlimit() == before


@pytest.mark.parametrize("kind", ["identity", "distribution"])
@pytest.mark.parametrize("qualified_reference", [False, True])
@pytest.mark.parametrize("qualified_key", [False, True])
def test_transform_aliases_resolve_and_discover_children(kind, qualified_reference, qualified_key):
    """CFG-027: transform lookup and lazy child discovery share namespace rules."""
    reference = f"core.{kind}" if qualified_reference else kind
    key = f"core.{kind}" if qualified_key else kind
    transform = {"type": reference}
    expected = "source"
    if kind == "distribution":
        child = {"type": "integer", "minValue": 7, "maxValue": 7}
        transform["choices"] = [{"spec": child}, {"spec": child}]
        expected = "7"
    field = {"type": "string", "values": ["source"], "transforms": [transform]}
    config = {"rows": 2, "format": "$x$", "types": {"x": field}}
    transforms = {key: api.build_extension_catalog().get_transform(kind)}
    assert list(api.generate(config, transforms=transforms, proof_mode="all")) == [expected] * 2


@pytest.mark.parametrize("reference", ["non_empty", "core.non_empty"])
@pytest.mark.parametrize("key", ["non_empty", "core.non_empty"])
@pytest.mark.parametrize("nested", [False, True])
def test_validator_aliases_preserve_validation(reference, key, nested):
    """CFG-028: either alias resolves through either registry spelling and still rejects."""
    validators = {key: api.build_extension_catalog().validators()["non_empty"]}
    field = {"type": "string", "values": ["ok"], "validators": [reference]}
    spec = {"type": "oneOf", "choices": [field]} if nested else field
    config = {"rows": 1, "format": "$x$", "types": {"x": spec}}
    assert list(api.generate(config, validators=validators)) == ["ok"]
    field["values"] = [""]
    with pytest.raises(api.ValidationError, match="non_empty"):
        list(api.generate(config, validators=validators))

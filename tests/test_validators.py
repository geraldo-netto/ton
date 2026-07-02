"""Tests for the validator extension point (PLUG-001)."""

from __future__ import annotations

import pytest

from ton import api
from ton._engine import Engine, TemplateError
from ton._validation import ValidationError
from ton.cli import main


class _EvenLength:
    type_name = "even_length"

    def validate(self, value: str) -> bool:
        return len(value) % 2 == 0


class _Never:
    type_name = "never"

    def validate(self, value: str) -> bool:
        del value
        return False


def _catalog_with(validator: object, name: str = "check") -> api.ExtensionCatalog:
    catalog = api.build_extension_catalog()
    catalog.register_validator("plugin", name, validator)
    return catalog


def _config(values: list[str], refs: list[str]) -> dict:
    return {
        "rows": 1,
        "format": "$v$",
        "types": {"v": {"type": "string", "values": values, "validators": refs}},
    }


def test_engine_runs_validator_and_passes() -> None:
    catalog = _catalog_with(_EvenLength())
    engine = Engine(_config(["ab"], ["plugin.check"]), validators=catalog.validators())
    assert list(engine) == ["ab"]


def test_engine_validator_failure_raises() -> None:
    catalog = _catalog_with(_EvenLength())
    engine = Engine(_config(["abc"], ["plugin.check"]), validators=catalog.validators())
    with pytest.raises(ValidationError, match="failed validator 'even_length'"):
        list(engine)


def test_engine_unknown_validator_reference_rejected() -> None:
    catalog = _catalog_with(_EvenLength())
    with pytest.raises(TemplateError, match="Unknown validator"):
        Engine(_config(["ab"], ["plugin.missing"]), validators=catalog.validators())


def test_validators_run_on_paired_values() -> None:
    catalog = _catalog_with(_Never())
    config = {
        "rows": 1,
        "format": "$w$",
        "types": {"w": {"type": "lmhash", "values": ["secret"], "validators": ["plugin.check"]}},
    }
    engine = Engine(config, validators=catalog.validators())
    with pytest.raises(ValidationError):
        list(engine)


def test_api_generate_accepts_validators() -> None:
    catalog = _catalog_with(_EvenLength())
    rows = list(api.generate(_config(["ab"], ["plugin.check"]), validators=catalog.validators()))
    assert rows == ["ab"]


def test_validate_config_rejects_unknown_validator() -> None:
    payload = _config(["ab"], ["plugin.missing"])
    with pytest.raises(api.ConfigError, match="Unknown validator"):
        api.validate_config(payload, catalog=_catalog_with(_EvenLength()))


def test_validate_config_accepts_known_validator() -> None:
    payload = _config(["ab"], ["plugin.check"])
    api.validate_config(payload, catalog=_catalog_with(_EvenLength()))


def test_validate_config_validators_must_be_list() -> None:
    payload = _config(["ab"], [])
    payload["types"]["v"]["validators"] = "plugin.check"
    with pytest.raises(api.ConfigError, match="'validators' must be a list"):
        api.validate_config(payload, catalog=_catalog_with(_EvenLength()))


def test_validate_config_validator_refs_must_be_strings() -> None:
    payload = _config(["ab"], [123])  # type: ignore[list-item]
    with pytest.raises(api.ConfigError, match="validator refs must be strings"):
        api.validate_config(payload, catalog=_catalog_with(_EvenLength()))


def test_list_namespaces_prints_validators(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--list-namespaces"]) == 0
    assert "validators:" in capsys.readouterr().out


def test_cli_validation_failure_exits_2(monkeypatch, write_config, capsys) -> None:
    from ton import cli

    catalog = _catalog_with(_Never())
    engine = Engine.from_config(_config(["x"], ["plugin.check"]), validators=catalog.validators())
    monkeypatch.setattr(cli, "_build_engine", lambda args, config: engine)
    config = write_config()
    assert main([str(config)]) == 2
    assert "validation failed" in capsys.readouterr().err

"""Exact integer-setting validation through public entry points (CFG-024)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from decimal import ROUND_UP, Context, Decimal, localcontext
from pathlib import Path

import pytest

from ton import api
from ton.cli import main
from ton.concurrency import fork_engine
from ton.generators.base import coerce_int

FRACTIONAL_DECIMALS = [
    "1.5",
    "-1.5",
    "0.5",
    "-0.5",
    "1.0000000000000000000000000001",
    "-1.0000000000000000000000000001",
    "9007199254740992.5",
    "1e-1000",
    "-1e-1000",
]
INVALID_DECIMALS = [
    *FRACTIONAL_DECIMALS,
    "NaN",
    "-NaN123",
    "sNaN",
    "-sNaN123",
    "Infinity",
    "-Infinity",
]

INTEGER_FIELDS = [
    pytest.param({"type": "integer", "minValue": 1, "maxValue": 9}, "minValue", id="integer-min"),
    pytest.param({"type": "integer", "minValue": 0, "maxValue": 1}, "maxValue", id="integer-max"),
    pytest.param(
        {"type": "decimal", "minValue": 0, "maxValue": 1, "decimals": 1},
        "decimals",
        id="decimal-scale",
    ),
    pytest.param({"type": "char", "values": ["a"], "maxChar": 1}, "maxChar", id="char-length"),
    pytest.param({"type": "bytes", "length": 1}, "length", id="bytes-length"),
    pytest.param({"type": "text", "count": 1}, "count", id="text-count"),
    pytest.param({"type": "sequence", "start": 1}, "start", id="sequence-start"),
    pytest.param({"type": "sequence", "step": 1}, "step", id="sequence-step"),
    pytest.param({"type": "sequence", "padWidth": 1}, "padWidth", id="sequence-padding"),
    pytest.param({"type": "uuid", "version": 1}, "version", id="uuid-version"),
    pytest.param(
        {"type": "sequence_of", "count": 1, "spec": {"type": "string", "values": ["a"]}},
        "count",
        id="sequence-of-count",
    ),
    pytest.param(
        {"type": "hash", "values": ["a"], "algorithm": "bcrypt", "rounds": 4},
        "rounds",
        id="bcrypt-rounds",
    ),
]


@pytest.fixture
def strict_decimal_context() -> Iterator[Context]:
    """Catch accidental rounding, overflow, float conversion and context mutation."""
    with localcontext(prec=2, Emax=9, Emin=-9, rounding=ROUND_UP) as context:
        for signal in context.traps:
            context.traps[signal] = True
        context.clear_flags()
        yield context
        assert not any(context.flags.values())
        assert (context.prec, context.Emax, context.Emin, context.rounding) == (2, 9, -9, ROUND_UP)
        assert all(context.traps.values())


@pytest.mark.parametrize("number", INVALID_DECIMALS)
@pytest.mark.parametrize("use_default", [False, True], ids=["explicit", "default"])
def test_coerce_int_rejects_inexact_and_nonfinite_decimals(
    number: str, use_default: bool, strict_decimal_context: Context
) -> None:
    raw = Decimal(number)
    spec = {} if use_default else {"value": raw}

    with pytest.raises(ValueError, match="test 'value' must be an integer"):
        coerce_int(spec, "value", type_name="test", default=raw)


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        pytest.param("0.00", 0, id="zero"),
        pytest.param("-0.00", 0, id="negative-zero"),
        pytest.param("3.000", 3, id="positive"),
        pytest.param("-3.000", -3, id="negative"),
        pytest.param("1e3", 1000, id="exponent"),
        pytest.param("9007199254740993.0", 9007199254740993, id="beyond-float-precision"),
        pytest.param("1e4300", 10**4300, id="beyond-int-string-limit"),
        pytest.param("-1e4300", -(10**4300), id="negative-beyond-int-string-limit"),
    ],
)
def test_coerce_int_accepts_exact_integral_decimals(
    number: str, expected: int, strict_decimal_context: Context
) -> None:
    actual = coerce_int({"value": Decimal(number)}, "value", type_name="test")

    assert type(actual) is int
    assert actual == expected


def _config(spec: dict) -> dict:
    return {"rows": 2, "format": "$x$", "types": {"x": spec}}


def _field_config(spec: dict, key: str, number: str, source: str, tmp_path: Path) -> dict:
    raw = Decimal(number)
    if source == "memory":
        return _config({**spec, key: raw})
    # Write a numeric token directly: float conversion or quoted Decimals would
    # hide the file-loading bug this suite must reproduce.
    payload = json.dumps(_config({**spec, key: "DECIMAL_TOKEN"}))
    assert payload.count('"DECIMAL_TOKEN"') == 1
    path = tmp_path / "integer-setting.json"
    path.write_text(payload.replace('"DECIMAL_TOKEN"', number), encoding="utf-8")
    config = api.load_config(str(path))
    loaded = config["types"]["x"][key]
    assert isinstance(loaded, Decimal)
    assert loaded.as_tuple() == raw.as_tuple()
    return config


def _assert_rejected(config: dict, operation: str, message: str) -> None:
    if operation == "validate":
        with pytest.raises(api.ConfigError, match=message):
            api.validate_config(config)
    else:
        with pytest.raises(api.TemplateError, match=message):
            list(api.generate(config, seed=1, proof_mode=operation))


@pytest.mark.parametrize(("spec", "key"), INTEGER_FIELDS)
@pytest.mark.parametrize("source", ["memory", "json"])
@pytest.mark.parametrize("operation", ["validate", "off", "all"])
def test_every_integer_setting_rejects_fractional_decimals(
    spec: dict, key: str, source: str, operation: str, tmp_path: Path
) -> None:
    config = _field_config(spec, key, f"{spec[key]}.5", source, tmp_path)

    _assert_rejected(config, operation, f"{spec['type']} '{key}' must be an integer")


@pytest.mark.parametrize(("spec", "key"), INTEGER_FIELDS)
@pytest.mark.parametrize("source", ["memory", "json"])
def test_every_integer_setting_accepts_integral_decimals(
    spec: dict, key: str, source: str, tmp_path: Path
) -> None:
    config = _field_config(spec, key, f"{spec[key]}.000", source, tmp_path)

    api.validate_config(config)
    expected = list(api.generate(_config(spec), seed=1, proof_mode="all"))
    assert list(api.generate(config, seed=1, proof_mode="all")) == expected


@pytest.mark.parametrize("number", INVALID_DECIMALS)
@pytest.mark.parametrize("operation", ["validate", "off", "all"])
def test_integer_bounds_reject_exact_fractions_and_nonfinite_decimals(
    number: str, operation: str
) -> None:
    raw = Decimal(number)
    config = _config({"type": "integer", "minValue": raw, "maxValue": raw})

    _assert_rejected(config, operation, "integer 'minValue' must be an integer")


def _write_singleton_bounds(tmp_path: Path, number: str) -> str:
    path = tmp_path / "bounds.json"
    path.write_text(
        '{"rows": 2, "format": "$x$", "types": {"x": {"type": "integer", '
        f'"minValue": {number}, "maxValue": {number}}}}}}}',
        encoding="utf-8",
    )
    return str(path)


@pytest.mark.parametrize("number", FRACTIONAL_DECIMALS)
@pytest.mark.parametrize("operation", ["validate", "off", "all"])
def test_json_integer_bounds_reject_exact_fractions(
    number: str, operation: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_singleton_bounds(tmp_path, number)
    options = ["--validate"] if operation == "validate" else ["--proof-check", operation]

    assert main([path, *options]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "integer 'minValue' must be an integer" in captured.err


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        ("0.0", "0"),
        ("-0.00", "0"),
        ("3.000", "3"),
        ("-3.000", "-3"),
        ("1e3", "1000"),
        ("9007199254740993.0", "9007199254740993"),
        pytest.param("1e4300", "1" + "0" * 4300, id="large-positive"),
        pytest.param("-1e4300", "-1" + "0" * 4300, id="large-negative"),
    ],
)
def test_integral_json_bounds_generate_exact_values(
    number: str, expected: str, tmp_path: Path
) -> None:
    path = _write_singleton_bounds(tmp_path, number)

    api.validate_config(api.load_config(path))
    assert list(api.generate_from_file(path, seed=1, proof_mode="all")) == [expected] * 2


@pytest.mark.parametrize("key", ["start", "step"])
@pytest.mark.parametrize("number", ["1.5", "-1.5", "1.0000000000000000000000000001"])
def test_worker_sequence_settings_reject_fractional_decimals(key: str, number: str) -> None:
    config = _config({"type": "sequence", key: Decimal(number)})

    with pytest.raises(ValueError, match=f"sequence '{key}' must be an integer"):
        fork_engine(config, parent_seed=1, worker_id=1, workers=2)

"""MAC grammar and configurable negative-data distribution (REL-039, REL-043, CFG-025)."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from math import sqrt
from pathlib import Path
from random import Random

import pytest

from ton import api
from ton._transforms import TransformResult
from ton.cli import main
from ton.generators.network import MACGenerator

VALID_MAC = re.compile(
    r"(?:[0-9a-fA-F]{12}|(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}|"
    r"(?:[0-9a-fA-F]{2}-){5}[0-9a-fA-F]{2})"
)
INVALID_OUIS = [
    "00  1a",
    "      ",
    "00\t\t1a",
    "00\n\n1a",
    "00:1A-2B",
    "0:01:A2:B",
    "001A2B:",
    ":001A2B",
    "00::1A:2B",
    "00--1A-2B",
    "00 1A 2B",
    " 001A2B ",
    "001A2B\n",
    "00.1A.2B",
    "001A2",
    "001A2B00",
    "001A2G",
    "００１Ａ２Ｂ",
    "",
    0,
    False,
    [],
    {},
]
INVALID_SEPARATORS = ["a", "A", "0", ".", " ", "\t", "\n", "é", "::", 1, False, None, []]


def _config(spec: dict, rows: int = 32) -> dict:
    return {"rows": rows, "format": "$x$", "types": {"x": {"type": "mac", **spec}}}


def _assert_config_rejected(spec: dict, key: str, operation: str) -> None:
    message = f"mac '{key}'"
    if operation == "prepare":
        with pytest.raises(ValueError, match=message):
            MACGenerator().prepare(spec)
    elif operation == "validate":
        with pytest.raises(api.ConfigError, match=message):
            api.validate_config(_config(spec))
    else:
        with pytest.raises(api.TemplateError, match=message):
            list(api.generate(_config(spec), proof_mode=operation))


@pytest.mark.parametrize("oui", INVALID_OUIS)
@pytest.mark.parametrize("operation", ["prepare", "validate", "off", "all"])
def test_malformed_oui_is_rejected_before_generation(oui: object, operation: str) -> None:
    """Never silently shorten or repair an invalid prefix (REL-039)."""
    _assert_config_rejected({"oui": oui}, "oui", operation)


@pytest.mark.parametrize("separator", INVALID_SEPARATORS)
@pytest.mark.parametrize("operation", ["prepare", "validate", "off", "all"])
def test_nonstandard_separator_is_rejected(separator: object, operation: str) -> None:
    """Normal MAC output must not use arbitrary delimiters (REL-043)."""
    _assert_config_rejected({"separator": separator}, "separator", operation)


@pytest.mark.parametrize("separator", [":", "-", ""])
@pytest.mark.parametrize("uppercase", [False, True])
@pytest.mark.parametrize("oui", [None, "001a2b", "00:1A:2b", "00-1a-2B", "FFFFFF", "000000"])
@pytest.mark.parametrize("seed", [0, 1, 123456])
def test_normal_macs_match_independent_grammar_and_prefix(
    separator: str, uppercase: bool, oui: str | None, seed: int
) -> None:
    spec = {"separator": separator, "uppercase": uppercase}
    if oui is not None:
        spec["oui"] = oui
    config = _config(spec)
    api.validate_config(config)
    rows = list(api.generate(config, seed=seed, proof_mode="all"))

    assert len(rows) == config["rows"]
    assert rows == list(api.generate(config, seed=seed, proof_mode="off"))
    for value in rows:
        assert VALID_MAC.fullmatch(value), value
        compact = value.replace(":", "").replace("-", "")
        assert len(bytes.fromhex(compact)) == 6
        assert compact == (compact.upper() if uppercase else compact.lower())
        if oui is not None:
            assert compact[:6].lower() == oui.replace(":", "").replace("-", "").lower()


@pytest.mark.parametrize("probability", [0, 0.25, 1])
@pytest.mark.parametrize(
    "value",
    [
        "",
        "garbage",
        "00:1a:2b:33",
        "00:1a:2b:33:44:55:66",
        "00:1a:2b:33:4g",
        "00:1a:2b:33:44:5g",
        "00-1a:2b:33:44",
        "00:1a:2b:33:44\n",
        "00:1a:2b:33:44:55\n",
        "00:1a:2b:33:  ",
        "00:1a:2b:33:44:  ",
        "00:1a:2b:33:４４",
        "00:1a:2b:33:44:５５",
        "00:1A:2B:33:44",
        "00:1A:2B:33:44:55",
        "00:ff:ee:33:44",
        "00:ff:ee:33:44:55",
    ],
)
def test_proof_rejects_values_outside_both_output_contracts(probability: float, value: str) -> None:
    generator = MACGenerator()
    prepared = generator.prepare({"oui": "00:1a:2b", "invalidProbability": probability})

    assert not generator.prove(prepared, TransformResult(value)).ok


@pytest.mark.parametrize(
    ("probability", "valid_ok", "invalid_ok"),
    [(0, True, False), (0.25, True, True), (1, False, True)],
)
def test_proof_only_accepts_shapes_with_nonzero_probability(
    probability: float, valid_ok: bool, invalid_ok: bool
) -> None:
    generator = MACGenerator()
    prepared = generator.prepare({"oui": "00:1a:2b", "invalidProbability": probability})

    assert generator.prove(prepared, TransformResult("00:1a:2b:33:44:55")).ok is valid_ok
    assert generator.prove(prepared, TransformResult("00:1a:2b:33:44")).ok is invalid_ok


@pytest.mark.parametrize("separator", [":", "-", ""])
@pytest.mark.parametrize("uppercase", [False, True])
@pytest.mark.parametrize("oui", [None, "00:1a:2b"])
@pytest.mark.parametrize("probability", [0, 0.25, 1])
@pytest.mark.parametrize("proof_mode", ["off", "sample", "all", "audit"])
def test_probability_controls_output_validity_with_all_formats_and_proof_modes(
    separator: str, uppercase: bool, oui: str | None, probability: float, proof_mode: str
) -> None:
    spec = {"separator": separator, "uppercase": uppercase, "invalidProbability": probability}
    if oui is not None:
        spec["oui"] = oui
    config = _config(spec, rows=100)
    api.validate_config(config)
    engine = api.Engine.from_config(config, seed=42, proof_mode=proof_mode, proof_sample_rate=3)
    rows = list(engine)
    invalid_count = 0
    for value in rows:
        compact = value.replace(":", "").replace("-", "")
        is_valid = VALID_MAC.fullmatch(value) is not None
        invalid_count += not is_valid
        assert re.fullmatch(r"[0-9a-fA-F]{10}|[0-9a-fA-F]{12}", compact), value
        assert len(compact) == (12 if is_valid else 10)
        assert value == separator.join(
            compact[index : index + 2] for index in range(0, len(compact), 2)
        )
        assert compact == (compact.upper() if uppercase else compact.lower())
        if oui is not None:
            assert compact[:6].lower() == "001a2b"
    assert invalid_count == 0 if probability == 0 else invalid_count > 0
    assert invalid_count == len(rows) if probability == 1 else invalid_count < len(rows)
    assert engine.proof_failures == ()
    assert rows == list(api.generate(config, seed=42, proof_mode="off"))


@pytest.mark.parametrize("probability", [0.1, 0.25, 0.5, 0.9])
@pytest.mark.parametrize("seed", [0, 42, 9876])
def test_mixed_distribution_matches_requested_probability(probability: float, seed: int) -> None:
    config = _config({"invalidProbability": probability}, rows=10_000)
    invalid_count = sum(VALID_MAC.fullmatch(row) is None for row in api.generate(config, seed=seed))
    expected = config["rows"] * probability
    tolerance = 6 * sqrt(config["rows"] * probability * (1 - probability))

    assert abs(invalid_count - expected) < tolerance


@pytest.mark.parametrize(
    "raw",
    [
        -0.1,
        1.1,
        True,
        False,
        "0.5",
        None,
        [],
        {},
        float("nan"),
        float("inf"),
        -float("inf"),
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal("-1e-1000"),
        Decimal("1.0000000000000000000000000001"),
        pytest.param(10**4300, id="huge-out-of-range-integer"),
    ],
)
@pytest.mark.parametrize("operation", ["prepare", "validate", "off", "all"])
def test_probability_requires_a_finite_number_in_unit_interval(raw: object, operation: str) -> None:
    _assert_config_rejected({"invalidProbability": raw}, "invalidProbability", operation)


class BoundaryRandom(Random):
    """Control the selection draw independently of the generated address bytes."""

    def __init__(self, draw: int, denominator: int | None) -> None:
        super().__init__(0)
        self.draw = draw
        self.denominator = denominator

    def randrange(self, stop: int) -> int:
        assert stop == self.denominator
        assert 0 <= self.draw < stop
        return self.draw

    def randbytes(self, length: int) -> bytes:
        return b"\xab" * length


@pytest.mark.parametrize(
    ("probability", "draw", "denominator", "valid"),
    [
        (0, 0, None, True),
        (1, 0, None, False),
        (Decimal("0.25"), 0, 4, False),
        (Decimal("0.25"), 1, 4, True),
        pytest.param(Decimal("1e-1000"), 0, 10**1000, False, id="tiny-invalid-draw"),
        pytest.param(Decimal("1e-1000"), 1, 10**1000, True, id="tiny-valid-draw"),
        pytest.param(
            Decimal("0." + "9" * 1000),
            10**1000 - 2,
            10**1000,
            False,
            id="near-one-invalid-draw",
        ),
        pytest.param(
            Decimal("0." + "9" * 1000),
            10**1000 - 1,
            10**1000,
            True,
            id="near-one-valid-draw",
        ),
    ],
)
def test_probability_sampling_preserves_exact_thresholds(
    probability: object, draw: int, denominator: int | None, valid: bool
) -> None:
    generator = MACGenerator()
    prepared = generator.prepare({"invalidProbability": probability})
    value = generator.generate(prepared, BoundaryRandom(draw, denominator))

    assert (VALID_MAC.fullmatch(value) is not None) is valid


@pytest.mark.parametrize("probability", ["0", "0.25", "1", "1e-1000"])
def test_json_probability_is_accepted_by_validation_and_cli(
    probability: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "mac.json"
    path.write_text(
        '{"rows": 100, "format": "$x$", "types": {"x": {"type": "mac", '
        f'"invalidProbability": {probability}}}}}}}',
        encoding="utf-8",
    )
    assert main([str(path), "--validate"]) == 0
    capsys.readouterr()
    assert main([str(path), "--seed", "42", "--proof-check", "all"]) == 0
    rows = capsys.readouterr().out.splitlines()
    assert len(rows) == 100
    assert rows == list(api.generate_from_file(str(path), seed=42, proof_mode="all"))


@pytest.mark.parametrize(
    "bad_spec",
    [
        {"oui": "00  1a"},
        {"separator": "a"},
        {"invalidProbability": -0.1},
        {"invalidProbability": 1.1},
        {"invalidProbability": True},
        {"invalidProbability": "0.25"},
    ],
)
def test_json_mac_configuration_errors_produce_no_rows(
    bad_spec: dict, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "bad-mac.json"
    path.write_text(json.dumps(_config(bad_spec)), encoding="utf-8")

    assert main([str(path), "--proof-check", "all"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert next(iter(bad_spec)) in captured.err


@pytest.mark.parametrize("probability", [0, 0.0, Decimal("-0.000")])
def test_explicit_zero_preserves_default_seeded_output(probability: object) -> None:
    config = _config({"oui": "00:1a:2b"})
    expected = list(api.generate(config, seed=1))
    config["types"]["x"]["invalidProbability"] = probability

    assert list(api.generate(config, seed=1, proof_mode="all")) == expected


@pytest.mark.parametrize("bad_spec", [{"oui": "00  1a"}, {"separator": "a"}])
def test_invalid_mode_does_not_bypass_configuration_validation(bad_spec: dict) -> None:
    _assert_config_rejected({**bad_spec, "invalidProbability": 1}, next(iter(bad_spec)), "prepare")

"""Unit tests for the built-in generators."""

from __future__ import annotations

from datetime import datetime
from random import Random

import pytest

from ton.generators import (
    BooleanGenerator,
    CharGenerator,
    DateGenerator,
    DecimalGenerator,
    IntegerGenerator,
    LMHashGenerator,
    StringGenerator,
)


def _rng() -> Random:
    return Random(42)


def _draw(generator, spec: dict) -> str:
    """Mimic the engine: prepare once, generate once."""
    return generator.generate(generator.prepare(spec), _rng())


def test_boolean_returns_one_of_two_literals() -> None:
    spec = {"whenTrue": "Y", "whenFalse": "N"}
    assert _draw(BooleanGenerator(), spec) in {"Y", "N"}


def test_integer_within_bounds_and_padded() -> None:
    spec = {"minValue": 1, "maxValue": 9999, "padWithZero": True}
    value = _draw(IntegerGenerator(), spec)
    assert value.isdigit()
    assert 1 <= int(value) <= 9999
    assert len(value) == len(str(spec["maxValue"]))


def test_integer_unpadded() -> None:
    spec = {"minValue": 1, "maxValue": 9, "padWithZero": False}
    value = _draw(IntegerGenerator(), spec)
    assert value in {str(i) for i in range(1, 10)}


def test_decimal_respects_decimals_arg() -> None:
    spec = {"minValue": 0.0, "maxValue": 1.0, "decimals": 3, "padWithZero": False}
    value = _draw(DecimalGenerator(), spec)
    fractional = value.split(".")[1] if "." in value else ""
    assert len(fractional) <= 3
    assert 0.0 <= float(value) <= 1.0


def test_char_concatenates_maxchar_values() -> None:
    assert _draw(CharGenerator(), {"values": ["A"], "maxChar": 4}) == "AAAA"


def test_string_picks_from_pool() -> None:
    values = ["AMD", "Intel", "ARM"]
    assert _draw(StringGenerator(), {"values": values}) in values


def test_string_rejects_empty_values() -> None:
    with pytest.raises(ValueError):
        StringGenerator().prepare({"values": []})


def test_char_rejects_missing_values() -> None:
    with pytest.raises(ValueError):
        CharGenerator().prepare({"maxChar": 2})


def test_integer_rejects_inverted_bounds() -> None:
    with pytest.raises(ValueError, match="maxValue"):
        IntegerGenerator().prepare({"minValue": 10, "maxValue": 1})


def test_decimal_rejects_inverted_bounds() -> None:
    with pytest.raises(ValueError, match="maxValue"):
        DecimalGenerator().prepare({"minValue": 1.0, "maxValue": 0.0, "decimals": 2})


def test_decimal_rejects_negative_decimals() -> None:
    with pytest.raises(ValueError, match="decimals"):
        DecimalGenerator().prepare({"minValue": 0.0, "maxValue": 1.0, "decimals": -1})


@pytest.mark.parametrize("bad", [0, -1, -100])
def test_char_rejects_non_positive_max_char(bad: int) -> None:
    with pytest.raises(ValueError, match="maxChar"):
        CharGenerator().prepare({"values": ["A"], "maxChar": bad})


def test_integer_pad_width_covers_negative_min() -> None:
    """Negative min and positive max should pad to the wider rendering (REL-014)."""
    gen = IntegerGenerator()
    prepared = gen.prepare({"minValue": -99, "maxValue": 99, "padWithZero": True})
    # len('-99') == 3, len('99') == 2 -> pad to 3.
    assert prepared.pad_width == 3
    # Positive number renders with same width as a negative one.
    rng = Random(0)
    for _ in range(50):
        value = gen.generate(prepared, rng)
        assert len(value) == 3


def test_decimal_pad_width_includes_decimal_point() -> None:
    """Padding must account for '-' and '.' chars (REL-014)."""
    gen = DecimalGenerator()
    prepared = gen.prepare(
        {"minValue": -9.99, "maxValue": 9.99, "decimals": 2, "padWithZero": True}
    )
    # '-9.99' is the widest possible output: 5 chars.
    assert prepared.pad_width == 5
    rng = Random(0)
    for _ in range(50):
        value = gen.generate(prepared, rng)
        assert len(value) == 5


def test_decimal_keeps_trailing_zeros_in_output() -> None:
    """f-string formatting (not round + str) preserves the requested width."""
    gen = DecimalGenerator()
    prepared = gen.prepare({"minValue": 1.0, "maxValue": 1.0, "decimals": 3, "padWithZero": False})
    assert gen.generate(prepared, Random(0)) == "1.000"


def test_lmhash_rejects_empty_values() -> None:
    with pytest.raises(ValueError):
        LMHashGenerator().prepare({"values": []})


def test_date_within_bounds_and_default_format() -> None:
    spec = {"minValue": "2000-01-01", "maxValue": "2000-12-31"}
    value = _draw(DateGenerator(), spec)
    moment = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    assert datetime(2000, 1, 1) <= moment <= datetime(2000, 12, 31, 23, 59, 59)


def test_date_custom_format_and_iso_datetime_bounds() -> None:
    spec = {
        "minValue": "2024-01-01T00:00:00",
        "maxValue": "2024-01-02T00:00:00",
        "format": "%Y%m%dT%H%M",
    }
    value = _draw(DateGenerator(), spec)
    moment = datetime.strptime(value, "%Y%m%dT%H%M")
    assert datetime(2024, 1, 1) <= moment <= datetime(2024, 1, 2)


def test_date_rejects_inverted_bounds() -> None:
    spec = {"minValue": "2024-12-31", "maxValue": "2024-01-01"}
    with pytest.raises(ValueError):
        DateGenerator().prepare(spec)


def test_date_prepare_parses_bounds_once() -> None:
    spec = {"minValue": "2024-01-01", "maxValue": "2024-12-31"}
    prepared = DateGenerator().prepare(spec)
    # Drawing many times should not re-parse the ISO strings.
    rng = Random(0)
    for _ in range(1000):
        DateGenerator().generate(prepared, rng)


def test_lmhash_pair_consistency() -> None:
    gen = LMHashGenerator()
    prepared = gen.prepare({"values": ["secret"]})
    plain, digest = gen.generate_pair(prepared, _rng())
    assert plain == "secret"
    assert digest == "878d8014606cda29677a44efa1353fc7"


def test_paired_generator_default_returns_primary() -> None:
    """generate() default keeps the primary half (ARCH-005)."""
    gen = LMHashGenerator()
    prepared = gen.prepare({"values": ["secret"]})
    # LMHashGenerator does not flip generate_returns_id, so generate()
    # returns the hash (primary) not the plaintext (id).
    assert gen.generate(prepared, _rng()) == "878d8014606cda29677a44efa1353fc7"


def test_paired_generator_knob_flips_to_id() -> None:
    """generate_returns_id=True flips the shortcut to the id half (ARCH-005)."""
    from typing import Any

    from ton.generators.base import PairedGenerator

    class FlippedHash(PairedGenerator):
        type_name = ""  # not registered
        generate_returns_id = True

        def generate_pair(self, prepared: Any, rng: Random) -> tuple:
            return "plain", "hash"

    assert FlippedHash().generate({}, _rng()) == "plain"


@pytest.mark.parametrize("seed", [0, 1, 7, 1337])
def test_same_seed_yields_same_value(seed: int) -> None:
    spec = {"minValue": 0, "maxValue": 1_000_000, "padWithZero": False}
    gen = IntegerGenerator()
    prepared = gen.prepare(spec)
    assert gen.generate(prepared, Random(seed)) == gen.generate(prepared, Random(seed))

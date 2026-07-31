"""Unit tests for the built-in generators."""

from __future__ import annotations

import builtins
from datetime import datetime
from decimal import Decimal
from random import Random
from typing import Any
from unittest import mock

import pytest

from ton.generators import (
    BooleanGenerator,
    CharGenerator,
    DateGenerator,
    DecimalGenerator,
    HashGenerator,
    IntegerGenerator,
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


@pytest.mark.parametrize("missing", ["whenTrue", "whenFalse"])
def test_boolean_reports_required_literal(missing: str) -> None:
    spec = {"whenTrue": "Y", "whenFalse": "N"}
    del spec[missing]

    with pytest.raises(ValueError, match=rf"boolean '{missing}' is required"):
        BooleanGenerator().prepare(spec)


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


def test_decimal_rejects_missing_bounds_with_friendly_error() -> None:
    with pytest.raises(ValueError, match="decimal 'minValue' is required"):
        DecimalGenerator().prepare({"maxValue": 1.0, "decimals": 2})


def test_decimal_rejects_non_numeric_bounds_with_friendly_error() -> None:
    with pytest.raises(ValueError, match="decimal 'maxValue' must be a number"):
        DecimalGenerator().prepare({"minValue": 0.0, "maxValue": "nope", "decimals": 2})


def test_decimal_rejects_range_without_representable_rounded_value() -> None:
    with pytest.raises(ValueError, match="representable"):
        DecimalGenerator().prepare({"minValue": 0.1, "maxValue": 0.9, "decimals": 0})


def test_decimal_step_bounds_do_not_shift_from_binary_float_error() -> None:
    prepared = DecimalGenerator().prepare({"minValue": 0.07, "maxValue": 0.29, "decimals": 2})

    assert prepared.min_step == 7
    assert prepared.max_step == 29


def test_decimal_accepts_equal_representable_fractional_bounds() -> None:
    prepared = DecimalGenerator().prepare({"minValue": 0.07, "maxValue": 0.07, "decimals": 2})

    assert DecimalGenerator().generate(prepared, Random(0)) == "0.07"


def test_decimal_draws_representable_steps_uniformly() -> None:
    generator = DecimalGenerator()
    prepared = generator.prepare({"minValue": 0, "maxValue": 0.2, "decimals": 1})
    rng = Random(42)
    counts = {value: 0 for value in ("0.0", "0.1", "0.2")}

    for _ in range(30_000):
        counts[generator.generate(prepared, rng)] += 1

    assert all(9_500 <= count <= 10_500 for count in counts.values())


def test_decimal_step_bounds_are_lazy_and_cached(monkeypatch) -> None:
    from ton.generators import decimal as decimal_module

    step_bounds = mock.Mock(wraps=decimal_module._step_bounds)
    monkeypatch.setattr(decimal_module, "_step_bounds", step_bounds)
    generator = DecimalGenerator()

    prepared = generator.prepare({"minValue": 0.0, "maxValue": 1.0, "decimals": 2})

    step_bounds.assert_not_called()
    assert prepared.scale == 100
    generator.generate(prepared, Random(0))
    generator.generate(prepared, Random(1))
    step_bounds.assert_called_once_with(Decimal("0.0"), Decimal("1.0"), 2)


def test_decimal_preserves_integer_bounds_above_binary_float_precision() -> None:
    generator = DecimalGenerator()
    prepared = generator.prepare(
        {"minValue": 9_007_199_254_740_992, "maxValue": 9_007_199_254_740_993, "decimals": 0}
    )
    rng = mock.Mock()
    rng.randint.side_effect = [prepared.min_step, prepared.max_step]

    assert generator.generate(prepared, rng) == "9007199254740992"
    assert generator.generate(prepared, rng) == "9007199254740993"


def test_decimal_formats_large_fixed_bounds_without_float_artifacts() -> None:
    generator = DecimalGenerator()
    bound = 10**80 + 1
    prepared = generator.prepare({"minValue": bound, "maxValue": bound, "decimals": 2})

    assert generator.generate(prepared, Random(0)) == f"{bound}.00"


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


def test_decimal_rounded_output_stays_inside_bounds() -> None:
    gen = DecimalGenerator()
    prepared = gen.prepare({"minValue": 0.0, "maxValue": 0.99, "decimals": 0})
    rng = Random(0)

    for _ in range(100):
        value = gen.generate(prepared, rng)
        assert value == "0"
        assert 0.0 <= float(value) <= 0.99


def test_ntlm_rejects_empty_values() -> None:
    with pytest.raises(ValueError):
        HashGenerator().prepare({"algorithm": "ntlm", "values": []})


@pytest.mark.parametrize(
    "algorithm,expected",
    [
        ("md5", "5ebe2294ecd0e0f08eab7690d2a6ee69"),
        ("sha1", "e5e9fa1ba31ecd1ae84f75caaa474f3a663f05f4"),
        ("sha256", "2bb80d537b1da3e38bd30361aa855686bde0eacd7162fef6a25fe97bf527a25b"),
        (
            "sha512",
            "bd2b1aaf7ef4f09be9f52ce2d8d599674d81aa9d6a"
            "4421696dc4d93dd0619d682ce56b4d64a9ef097761ced99"
            "e0f67265b5f76085e5b0ee7ca4696b2ad6fe2b2",
        ),
        ("ntlm", "878d8014606cda29677a44efa1353fc7"),
    ],
)
def test_hash_generator_algorithms(algorithm: str, expected: str) -> None:
    gen = HashGenerator()
    prepared = gen.prepare({"algorithm": algorithm, "values": ["secret"]})
    plain, digest = gen.generate_pair(prepared, _rng())
    assert plain == "secret"
    assert digest == expected


def test_hash_generator_defaults_to_sha256() -> None:
    gen = HashGenerator()
    prepared = gen.prepare({"values": ["secret"]})
    assert gen.generate(prepared, _rng()) == (
        "2bb80d537b1da3e38bd30361aa855686bde0eacd7162fef6a25fe97bf527a25b"
    )


def test_hash_generator_rejects_unknown_algorithm() -> None:
    with pytest.raises(ValueError, match="algorithm"):
        HashGenerator().prepare({"algorithm": "scrypt", "values": ["secret"]})


def test_hash_generator_bcrypt_is_deterministic() -> None:
    gen = HashGenerator()
    prepared = gen.prepare({"algorithm": "bcrypt", "rounds": 4, "values": ["secret"]})
    assert gen.generate(prepared, _rng()) == (
        "$2b$04$I5eLS1qbm8MJyuLfomTUfeuzPdxYbe9Z9taDPxzfKRS1bf.1N9wOi"
    )


def test_hash_generator_bcrypt_hashes_selected_values_once(monkeypatch) -> None:
    from ton.generators import hash as hash_module

    words = [f"secret-{index}" for index in range(10_000)]
    digest = mock.Mock(side_effect=lambda plaintext, rounds: f"{plaintext}:{rounds}")
    monkeypatch.setattr(hash_module, "_bcrypt_digest", digest)
    rng = mock.Mock()
    rng.choice.side_effect = [words[-1], words[-1], words[0]]
    generator = HashGenerator()

    prepared = generator.prepare({"algorithm": "bcrypt", "rounds": 4, "values": words})

    digest.assert_not_called()
    assert generator.generate_pair(prepared, rng) == (words[-1], f"{words[-1]}:4")
    assert generator.generate_pair(prepared, rng) == (words[-1], f"{words[-1]}:4")
    assert generator.generate_pair(prepared, rng) == (words[0], f"{words[0]}:4")
    assert digest.call_args_list == [mock.call(words[-1], 4), mock.call(words[0], 4)]
    assert len(prepared.words) == len(words)
    assert len(prepared.cache) == 2


def test_hash_generator_digests_selected_values_once(monkeypatch) -> None:
    from ton.generators import hash as hash_module

    words = [f"secret-{index}" for index in range(10_000)]
    digest = mock.Mock(side_effect=lambda data: data.decode().upper())
    monkeypatch.setitem(hash_module._HASHERS, "sha256", digest)
    rng = mock.Mock()
    rng.choice.side_effect = [words[-1], words[-1], words[0]]
    generator = HashGenerator()

    prepared = generator.prepare({"algorithm": "sha256", "values": words})

    digest.assert_not_called()
    assert generator.generate_pair(prepared, rng) == (words[-1], words[-1].upper())
    assert generator.generate_pair(prepared, rng) == (words[-1], words[-1].upper())
    assert generator.generate_pair(prepared, rng) == (words[0], words[0].upper())
    assert digest.call_args_list == [mock.call(words[-1].encode()), mock.call(words[0].encode())]
    assert len(prepared.cache) == 2


def test_hash_generator_rejects_bad_bcrypt_rounds() -> None:
    with pytest.raises(ValueError, match="rounds"):
        HashGenerator().prepare({"algorithm": "bcrypt", "rounds": 3, "values": ["secret"]})


@pytest.mark.parametrize("value", ["x" * 73, "é" * 37])
def test_hash_generator_rejects_bcrypt_plaintext_over_72_bytes(value: str) -> None:
    with pytest.raises(ValueError, match="at most 72 UTF-8 bytes"):
        HashGenerator().prepare({"algorithm": "bcrypt", "rounds": 4, "values": [value]})


def test_hash_generator_accepts_full_bcrypt_cost_range() -> None:
    prepared = HashGenerator().prepare({"algorithm": "bcrypt", "rounds": 13, "values": ["secret"]})
    assert prepared.rounds == 13


def test_hash_generator_rejects_unrepresentable_bcrypt_rounds() -> None:
    with pytest.raises(ValueError, match="between 4 and 31"):
        HashGenerator().prepare(
            {
                "algorithm": "bcrypt",
                "rounds": 32,
                "values": ["secret"],
            }
        )


def test_hash_generator_reports_missing_bcrypt_dependency(monkeypatch) -> None:
    real_import = builtins.__import__

    def _blocked_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "bcrypt":
            raise ImportError("blocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)
    with pytest.raises(ValueError, match=r"ton\[bcrypt\]"):
        HashGenerator().prepare({"algorithm": "bcrypt", "rounds": 4, "values": ["secret"]})


def test_hash_generator_bcrypt_base64_handles_two_byte_tail() -> None:
    from ton.generators.hash import _bcrypt_base64

    assert _bcrypt_base64(b"ab") == b"WUG"


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


def test_date_rejects_non_portable_format_directive() -> None:
    spec = {"minValue": "2000-01-01", "maxValue": "2000-12-31", "format": "%-d/%m"}
    with pytest.raises(ValueError, match="non-portable directive"):
        DateGenerator().prepare(spec)


@pytest.mark.parametrize("directive", ["%s", "%Q", "%"])
def test_date_rejects_unsupported_directives(directive: str) -> None:
    with pytest.raises(ValueError, match="non-portable"):
        DateGenerator().prepare(
            {"minValue": "2000-01-01", "maxValue": "2000-12-31", "format": directive}
        )


def test_date_rejects_non_string_format() -> None:
    spec = {"minValue": "2000-01-01", "maxValue": "2000-12-31", "format": 123}
    with pytest.raises(ValueError, match="must be a string"):
        DateGenerator().prepare(spec)


def test_date_allows_literal_percent_before_flag() -> None:
    # '%%-d' renders a literal '%-d', not the non-portable %- flag.
    spec = {"minValue": "2000-01-01", "maxValue": "2000-01-01", "format": "%%-d"}
    value = _draw(DateGenerator(), spec)
    assert value == "%-d"


def test_date_prepare_parses_bounds_once() -> None:
    spec = {"minValue": "2024-01-01", "maxValue": "2024-12-31"}
    prepared = DateGenerator().prepare(spec)
    # Drawing many times should not re-parse the ISO strings.
    rng = Random(0)
    for _ in range(1000):
        DateGenerator().generate(prepared, rng)


def test_ntlm_pair_consistency() -> None:
    gen = HashGenerator()
    prepared = gen.prepare({"algorithm": "ntlm", "values": ["secret"]})
    plain, digest = gen.generate_pair(prepared, _rng())
    assert plain == "secret"
    assert digest == "878d8014606cda29677a44efa1353fc7"


def test_paired_generator_default_returns_primary() -> None:
    """generate() default keeps the primary half (ARCH-005)."""
    gen = HashGenerator()
    prepared = gen.prepare({"algorithm": "ntlm", "values": ["secret"]})
    # HashGenerator does not flip generate_returns_id, so generate()
    # returns the hash (primary) not the plaintext (id).
    assert gen.generate(prepared, _rng()) == "878d8014606cda29677a44efa1353fc7"


def test_paired_generator_knob_flips_to_id() -> None:
    """generate_returns_id=True flips the shortcut to the id half (ARCH-005)."""
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


@pytest.mark.parametrize(
    ("generator", "spec"),
    [
        (IntegerGenerator(), {"minValue": 1, "maxValue": 2, "padWithZero": "false"}),
        (DecimalGenerator(), {"minValue": 1, "maxValue": 2, "decimals": 1, "padWithZero": 1}),
    ],
)
def test_boolean_options_reject_non_booleans(generator, spec: dict) -> None:
    with pytest.raises(ValueError, match="must be a boolean"):
        generator.prepare(spec)

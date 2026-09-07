"""Unit tests for the built-in generators."""

from __future__ import annotations

import builtins
from datetime import datetime
from decimal import Decimal
from random import Random
from typing import Any
from unittest import mock

import pytest

from ton import api
from ton._transforms import TransformResult
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
    generator = BooleanGenerator()

    with pytest.raises(ValueError, match=rf"boolean '{missing}' is required"):
        generator.prepare(spec)


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
    generator = StringGenerator()
    with pytest.raises(ValueError):
        generator.prepare({"values": []})


def test_char_rejects_missing_values() -> None:
    generator = CharGenerator()
    with pytest.raises(ValueError):
        generator.prepare({"maxChar": 2})


def test_integer_rejects_inverted_bounds() -> None:
    generator = IntegerGenerator()
    with pytest.raises(ValueError, match="maxValue"):
        generator.prepare({"minValue": 10, "maxValue": 1})


def test_decimal_rejects_inverted_bounds() -> None:
    generator = DecimalGenerator()
    with pytest.raises(ValueError, match="maxValue"):
        generator.prepare({"minValue": 1.0, "maxValue": 0.0, "decimals": 2})


def test_decimal_rejects_missing_bounds_with_friendly_error() -> None:
    generator = DecimalGenerator()
    with pytest.raises(ValueError, match="decimal 'minValue' is required"):
        generator.prepare({"maxValue": 1.0, "decimals": 2})


def test_decimal_rejects_non_numeric_bounds_with_friendly_error() -> None:
    generator = DecimalGenerator()
    with pytest.raises(ValueError, match="decimal 'maxValue' must be a number"):
        generator.prepare({"minValue": 0.0, "maxValue": "nope", "decimals": 2})


def test_decimal_rejects_range_without_representable_rounded_value() -> None:
    generator = DecimalGenerator()
    with pytest.raises(ValueError, match="representable"):
        generator.prepare({"minValue": 0.1, "maxValue": 0.9, "decimals": 0})


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
    generator = DecimalGenerator()
    with pytest.raises(ValueError, match="decimals"):
        generator.prepare({"minValue": 0.0, "maxValue": 1.0, "decimals": -1})


@pytest.mark.parametrize("bad", [0, -1, -100])
def test_char_rejects_non_positive_max_char(bad: int) -> None:
    generator = CharGenerator()
    with pytest.raises(ValueError, match="maxChar"):
        generator.prepare({"values": ["A"], "maxChar": bad})


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
    generator = HashGenerator()
    with pytest.raises(ValueError):
        generator.prepare({"algorithm": "ntlm", "values": []})


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
    generator = HashGenerator()
    with pytest.raises(ValueError, match="algorithm"):
        generator.prepare({"algorithm": "scrypt", "values": ["secret"]})


def test_hash_generator_bcrypt_is_deterministic() -> None:
    gen = HashGenerator()
    prepared = gen.prepare({"algorithm": "bcrypt", "rounds": 4, "values": ["secret"]})
    assert gen.generate(prepared, _rng()) == (
        "$2b$04$I5eLS1qbm8MJyuLfomTUfeuzPdxYbe9Z9taDPxzfKRS1bf.1N9wOi"
    )


def test_hash_generator_bcrypt_cache_is_operator_controlled(monkeypatch) -> None:
    from ton.generators import hash as hash_module

    words = [f"secret-{index}" for index in range(10_000)]
    digest = mock.Mock(side_effect=lambda plaintext, rounds: f"{plaintext}:{rounds}")
    monkeypatch.setattr(hash_module, "_bcrypt_digest", digest)
    rng = mock.Mock()
    rng.choice.side_effect = [words[-1], words[-1], words[0]]
    generator = HashGenerator()

    prepared = generator.prepare(
        {"algorithm": "bcrypt", "rounds": 4, "values": words, "cache": True}
    )

    digest.assert_not_called()
    assert generator.generate_pair(prepared, rng) == (words[-1], f"{words[-1]}:4")
    assert generator.generate_pair(prepared, rng) == (words[-1], f"{words[-1]}:4")
    assert generator.generate_pair(prepared, rng) == (words[0], f"{words[0]}:4")
    assert digest.call_args_list == [mock.call(words[-1], 4), mock.call(words[0], 4)]
    assert len(prepared.words) == len(words)
    assert prepared.cache is not None
    assert len(prepared.cache) == 2


def test_hash_generator_does_not_cache_inexpensive_digests(monkeypatch) -> None:
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
    assert digest.call_args_list == [
        mock.call(words[-1].encode()),
        mock.call(words[-1].encode()),
        mock.call(words[0].encode()),
    ]


def test_hash_generator_bcrypt_cache_defaults_off(monkeypatch) -> None:
    from ton.generators import hash as hash_module

    digest = mock.Mock(return_value="digest")
    monkeypatch.setattr(hash_module, "_bcrypt_digest", digest)
    generator = HashGenerator()
    prepared = generator.prepare({"algorithm": "bcrypt", "rounds": 4, "values": ["secret"]})

    generator.generate_pair(prepared, _rng())
    generator.generate_pair(prepared, _rng())

    assert prepared.cache is None
    assert digest.call_count == 2


def test_hash_generator_rejects_cache_for_inexpensive_digest() -> None:
    generator = HashGenerator()
    with pytest.raises(ValueError, match="only for the bcrypt"):
        generator.prepare({"algorithm": "sha256", "values": ["secret"], "cache": True})


def test_hash_generator_rejects_bad_bcrypt_rounds() -> None:
    generator = HashGenerator()
    with pytest.raises(ValueError, match="rounds"):
        generator.prepare({"algorithm": "bcrypt", "rounds": 3, "values": ["secret"]})


@pytest.mark.parametrize("value", ["x" * 73, "é" * 37])
def test_hash_generator_rejects_bcrypt_plaintext_over_72_bytes(value: str) -> None:
    generator = HashGenerator()
    with pytest.raises(ValueError, match="at most 72 UTF-8 bytes"):
        generator.prepare({"algorithm": "bcrypt", "rounds": 4, "values": [value]})


def test_hash_generator_accepts_full_bcrypt_cost_range() -> None:
    prepared = HashGenerator().prepare({"algorithm": "bcrypt", "rounds": 13, "values": ["secret"]})
    assert prepared.rounds == 13


def test_hash_generator_rejects_unrepresentable_bcrypt_rounds() -> None:
    generator = HashGenerator()
    with pytest.raises(ValueError, match="between 4 and 31"):
        generator.prepare(
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
    generator = HashGenerator()
    with pytest.raises(ValueError, match=r"ton\[bcrypt\]"):
        generator.prepare({"algorithm": "bcrypt", "rounds": 4, "values": ["secret"]})


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


def test_date_formats_every_directive_without_locale_dependence() -> None:
    spec = {
        "minValue": "2024-01-01T13:05:06.123456+00:00",
        "maxValue": "2024-01-01T13:05:06.123456+00:00",
        "format": "%a|%A|%b|%B|%c|%d|%H|%I|%j|%m|%M|%p|%S|%U|%w|%W|%x|%X|%y|%Y|%z|%Z|%f|%%",
    }

    generator = DateGenerator()
    prepared = generator.prepare(spec)
    value = generator.generate(prepared, _rng())

    assert value == (
        "Mon|Monday|Jan|January|Mon Jan  1 13:05:06 2024|01|13|01|001|01|05|PM|06|"
        "00|1|01|01/01/24|13:05:06|24|2024|+0000|UTC|123456|%"
    )
    assert generator.prove(prepared, TransformResult(value)).ok


@pytest.mark.parametrize(
    ("offset", "numeric", "name"),
    [
        ("+05:30", "+0530", "UTC+05:30"),
        ("-02:03:04.000005", "-020304.000005", "UTC-02:03:04.000005"),
    ],
)
def test_date_formats_timezone_offsets_portably(offset: str, numeric: str, name: str) -> None:
    bound = f"2024-01-01T00:00:00{offset}"
    assert (
        _draw(DateGenerator(), {"minValue": bound, "maxValue": bound, "format": "%z|%Z"})
        == f"{numeric}|{name}"
    )


def test_date_formats_naive_timezone_as_empty() -> None:
    spec = {
        "minValue": "2024-01-01T00:00:00",
        "maxValue": "2024-01-01T00:00:00",
        "format": "%z|%Z",
    }

    assert _draw(DateGenerator(), spec) == "|"


def test_date_rejects_inverted_bounds() -> None:
    spec = {"minValue": "2024-12-31", "maxValue": "2024-01-01"}
    generator = DateGenerator()
    with pytest.raises(ValueError):
        generator.prepare(spec)


def test_date_rejects_non_portable_format_directive() -> None:
    spec = {"minValue": "2000-01-01", "maxValue": "2000-12-31", "format": "%-d/%m"}
    generator = DateGenerator()
    with pytest.raises(ValueError, match="non-portable directive"):
        generator.prepare(spec)


@pytest.mark.parametrize("directive", ["%s", "%Q", "%"])
def test_date_rejects_unsupported_directives(directive: str) -> None:
    generator = DateGenerator()
    with pytest.raises(ValueError, match="non-portable"):
        generator.prepare({"minValue": "2000-01-01", "maxValue": "2000-12-31", "format": directive})


def test_date_rejects_non_string_format() -> None:
    spec = {"minValue": "2000-01-01", "maxValue": "2000-12-31", "format": 123}
    generator = DateGenerator()
    with pytest.raises(ValueError, match="must be a string"):
        generator.prepare(spec)


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


def test_date_proof_rejects_out_of_range_and_invalid_calendar_values() -> None:
    generator = DateGenerator()
    prepared = generator.prepare(
        {
            "minValue": "2024-01-01",
            "maxValue": "2024-01-02",
            "format": "%Y-%m-%d",
        }
    )

    assert not generator.prove(prepared, TransformResult("2099-12-31")).ok
    assert not generator.prove(prepared, TransformResult("2024-02-30")).ok


def test_date_proof_rejects_inconsistent_weekday() -> None:
    generator = DateGenerator()
    prepared = generator.prepare(
        {
            "minValue": "2024-01-01",
            "maxValue": "2024-01-01",
            "format": "%Y-%m-%d %A",
        }
    )

    proof = generator.prove(prepared, TransformResult("2024-01-01 Tuesday"))

    assert not proof.ok
    assert "inconsistent" in proof.reason


@pytest.mark.parametrize(
    ("fmt", "value"),
    [
        ("%Y-%m-%d %H:%M:%S.%f", "2024-01-01 13:05:06.123456"),
        ("%Y-%m-%d %H:%M", "2024-01-01 13:05"),
        ("%Y-%m-%d %H", "2024-01-01 13"),
        ("%x", "01/01/24"),
    ],
)
def test_date_proof_handles_each_output_resolution(fmt: str, value: str) -> None:
    generator = DateGenerator()
    prepared = generator.prepare(
        {
            "minValue": "2024-01-01T13:05:06.123456",
            "maxValue": "2024-01-01T13:05:06.123456",
            "format": fmt,
        }
    )

    assert generator.prove(prepared, TransformResult(value)).ok


def test_date_proof_aligns_omitted_timezone_with_aware_bounds() -> None:
    generator = DateGenerator()
    prepared = generator.prepare(
        {
            "minValue": "2024-01-01T00:00:00+05:30",
            "maxValue": "2024-01-01T00:00:00+05:30",
            "format": "%Y-%m-%d",
        }
    )

    assert generator.prove(prepared, TransformResult("2024-01-01")).ok


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
    first = gen.generate(prepared, Random(seed))
    second = gen.generate(prepared, Random(seed))
    assert first == second


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


@pytest.mark.parametrize(
    "fmt",
    ["%Y-%m-%d %f", "%Y-%m-%d %S", "%Y-%m-%d %M", "%Y-%m-%d %H", "%Y-%m-%d", "%Y-%m-%d %I %p"],
)
def test_partial_time_formats_pass_their_own_strict_proof(fmt: str) -> None:
    """Omitted components must widen the proof hull, not force midnight (REL-024)."""
    bound = "2024-01-01T12:34:56.123456"
    config = {
        "rows": 1,
        "format": "$x$",
        "types": {"x": {"type": "date", "minValue": bound, "maxValue": bound, "format": fmt}},
    }

    assert len(list(api.generate(config, seed=1, proof_mode="all"))) == 1


def test_partial_time_format_still_rejects_an_out_of_range_date() -> None:
    """Widening for omitted components must not make the interval check vacuous."""
    from ton.generators.base import PreparationContext
    from ton.generators.date import DateGenerator

    generator = DateGenerator()
    prepared = generator.prepare(
        {
            "minValue": "2024-01-01T00:00:00",
            "maxValue": "2024-01-01T23:59:59.999999",
            "format": "%Y-%m-%d %f",
        },
        PreparationContext({}),
    )

    assert generator.prove(prepared, TransformResult("2024-01-01 123456")).ok
    assert not generator.prove(prepared, TransformResult("2024-06-09 123456")).ok

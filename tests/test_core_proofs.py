"""Proof hooks for every non-composite built-in generator."""

from __future__ import annotations

from random import Random
from typing import Any

import pytest

from ton._transforms import TransformResult
from ton.generators import (
    BooleanGenerator,
    BytesGenerator,
    CharGenerator,
    DateGenerator,
    DecimalGenerator,
    EmailGenerator,
    HashGenerator,
    IntegerGenerator,
    IPv4Generator,
    IPv6Generator,
    MACGenerator,
    NameGenerator,
    PhoneGenerator,
    RegexGenerator,
    SequenceGenerator,
    StringGenerator,
    TextGenerator,
    TimestampUnixGenerator,
    UUIDGenerator,
)

_CASES: tuple[tuple[Any, dict[str, Any]], ...] = (
    (BooleanGenerator(), {"whenTrue": "yes", "whenFalse": "no"}),
    (BytesGenerator(), {"length": 8, "encoding": "base64"}),
    (BytesGenerator(), {"length": 8, "encoding": "hex"}),
    (BytesGenerator(), {"length": 8, "encoding": "base32"}),
    (CharGenerator(), {"values": ["A", "B"], "maxChar": 4}),
    (DateGenerator(), {"minValue": "2024-01-01", "maxValue": "2024-01-02"}),
    (DecimalGenerator(), {"minValue": 1, "maxValue": 2, "decimals": 2}),
    (EmailGenerator(), {"domains": ["example.test"]}),
    (HashGenerator(), {"algorithm": "sha256", "values": ["secret"]}),
    (IPv4Generator(), {"cidr": "10.0.0.0/24"}),
    (IPv6Generator(), {"cidr": "2001:db8::/120"}),
    (IntegerGenerator(), {"minValue": 1, "maxValue": 9}),
    (MACGenerator(), {"oui": "00:1A:2B"}),
    (NameGenerator(), {"style": "full"}),
    (NameGenerator(), {"style": "given"}),
    (NameGenerator(), {"style": "family"}),
    (PhoneGenerator(), {"format": "+##"}),
    (RegexGenerator(), {"pattern": "[A-Z]{3}"}),
    (SequenceGenerator(), {"start": 1, "step": 2}),
    (StringGenerator(), {"values": ["valid"]}),
    (TextGenerator(), {"unit": "sentences", "count": 2}),
    (TextGenerator(), {"unit": "words", "count": 2}),
    (
        TimestampUnixGenerator(),
        {"minValue": "2024-01-01", "maxValue": "2024-01-02", "unit": "millis"},
    ),
    (UUIDGenerator(), {"version": 4}),
)


@pytest.mark.parametrize(("generator", "spec"), _CASES, ids=lambda value: type(value).__name__)
def test_core_proof_accepts_generated_value_and_rejects_mutation(generator, spec) -> None:
    prepared = generator.prepare(spec)
    if isinstance(generator, HashGenerator):
        plaintext, digest = generator.generate_pair(prepared, Random(0))
        generated = TransformResult(digest, id_value=plaintext)
        mutated = TransformResult("not-the-digest", id_value=plaintext)
    else:
        generated = TransformResult(generator.generate(prepared, Random(0)))
        mutated = TransformResult("!invalid!")

    assert generator.prove(prepared, generated).ok
    assert not generator.prove(prepared, mutated).ok


@pytest.mark.parametrize("padding", [False, True])
@pytest.mark.parametrize("value", ["1.5", "-1.5", "0.1", "1e-1", "1.0"])
def test_decimal_zero_scale_rejects_fractional_renderings(padding, value) -> None:
    """REL-042: zero-scale proof enforces the integral generation contract."""
    generator = DecimalGenerator()
    prepared = generator.prepare(
        {"minValue": -100, "maxValue": 100, "decimals": 0, "padWithZero": padding}
    )
    assert not generator.prove(prepared, TransformResult(value)).ok
    for seed in range(20):
        generated = generator.generate(prepared, Random(seed))
        assert "." not in generated
        assert generator.prove(prepared, TransformResult(generated)).ok


def test_hash_proof_computes_uncached_digest_and_rejects_missing_plaintext() -> None:
    generator = HashGenerator()
    spec = {"algorithm": "sha256", "values": ["secret"]}
    prepared = generator.prepare(spec)

    assert generator.prove(
        prepared,
        TransformResult(
            "2bb80d537b1da3e38bd30361aa855686bde0eacd7162fef6a25fe97bf527a25b",
            id_value="secret",
        ),
    ).ok
    assert not generator.prove(prepared, TransformResult("digest")).ok


def test_bcrypt_proof_computes_uncached_digest() -> None:
    generator = HashGenerator()
    prepared = generator.prepare({"algorithm": "bcrypt", "rounds": 4, "values": ["secret"]})
    result = TransformResult(
        "$2b$04$I5eLS1qbm8MJyuLfomTUfeuzPdxYbe9Z9taDPxzfKRS1bf.1N9wOi",
        id_value="secret",
    )

    assert generator.prove(prepared, result).ok


def test_phone_proof_rejects_non_digit_after_matching_prefix() -> None:
    generator = PhoneGenerator()
    prepared = generator.prepare({"format": "+##"})

    assert not generator.prove(prepared, TransformResult("+x1")).ok


@pytest.mark.parametrize("value", [True, "Infinity"])
def test_decimal_rejects_non_finite_or_boolean_bound(value: object) -> None:
    generator = DecimalGenerator()
    with pytest.raises(ValueError, match="must be a .*number"):
        generator.prepare({"minValue": value, "maxValue": 1, "decimals": 2})


@pytest.mark.parametrize(
    ("lower", "upper", "valid", "invalid"),
    [
        (1, 99, "01", [" 1", "+1", "1 ", "1", "001"]),
        (-99, -1, "-01", [" -1", "-1 ", "-1", "-001"]),
        (-99, 99, "001", [" +1", "+01", " 01", "01"]),
    ],
)
def test_integer_proof_requires_exact_zero_padding(lower, upper, valid, invalid) -> None:
    """REL-051: equal width alone does not establish the padding contract."""
    generator = IntegerGenerator()
    prepared = generator.prepare({"minValue": lower, "maxValue": upper, "padWithZero": True})
    assert generator.prove(prepared, TransformResult(valid)).ok
    for value in invalid:
        assert not generator.prove(prepared, TransformResult(value)).ok, repr(value)


@pytest.mark.parametrize("value", ["+1", " 1", "1 ", "01", "-0", "١"])
def test_integer_proof_requires_canonical_unpadded_digits(value) -> None:
    """REL-051: integer parsing must not admit spellings generation cannot emit."""
    generator = IntegerGenerator()
    prepared = generator.prepare({"minValue": -9, "maxValue": 9})
    assert generator.prove(prepared, TransformResult("1")).ok
    assert not generator.prove(prepared, TransformResult(value)).ok


@pytest.mark.parametrize(
    "value", ["1.0e0", "1.0_0", "1.00 ", " 1.000", "+1.000", "01.000", "١.٠٠٠"]
)
def test_decimal_proof_requires_fixed_point_digits(value) -> None:
    """REL-052: parseable decimal values need not have the generated syntax."""
    generator = DecimalGenerator()
    prepared = generator.prepare({"minValue": 1, "maxValue": 1, "decimals": 3})
    assert generator.prove(prepared, TransformResult("1.000")).ok
    assert not generator.prove(prepared, TransformResult(value)).ok


@pytest.mark.parametrize("padding", [False, True])
@pytest.mark.parametrize("scale", [0, 3])
def test_decimal_proof_validates_boundaries_and_padding(padding, scale) -> None:
    """REL-052: exact signs, scale and padding survive negative/cross-zero bounds."""
    generator = DecimalGenerator()
    prepared = generator.prepare(
        {"minValue": -99, "maxValue": 99, "decimals": scale, "padWithZero": padding}
    )
    for whole in ["-99", "-1", "0", "1", "99"]:
        value = whole + (".000" if scale else "")
        expected = value.zfill(7 if scale else 3) if padding else value
        assert generator.prove(prepared, TransformResult(expected)).ok
        assert not generator.prove(prepared, TransformResult(" " + expected[1:])).ok
    for value in ["-100", "100", "-0"]:
        rendered = value + (".000" if scale else "")
        rendered = rendered.zfill(7 if scale else 3) if padding else rendered
        assert not generator.prove(prepared, TransformResult(rendered)).ok

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

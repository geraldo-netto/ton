"""Tests for the name / email / phone generators."""

from __future__ import annotations

import re
from random import Random

import pytest

from ton._transforms import TransformResult
from ton.generators.identity import EmailGenerator, NameGenerator, PhoneGenerator


def test_name_default_is_two_words() -> None:
    gen = NameGenerator()
    prepared = gen.prepare({})
    value = gen.generate(prepared, Random(0))
    assert len(value.split()) == 2


def test_name_given_only_is_single_word() -> None:
    gen = NameGenerator()
    prepared = gen.prepare({"style": "given"})
    value = gen.generate(prepared, Random(0))
    assert " " not in value


def test_name_rejects_unknown_style() -> None:
    generator = NameGenerator()
    with pytest.raises(ValueError):
        generator.prepare({"style": "nickname"})


def test_email_uses_lowercase_local_and_known_domain() -> None:
    gen = EmailGenerator()
    prepared = gen.prepare({"domains": ["example.com"]})
    value = gen.generate(prepared, Random(0))
    local, _, domain = value.partition("@")
    assert local == local.lower()
    assert "." in local
    assert domain == "example.com"


def test_email_rejects_empty_domains() -> None:
    generator = EmailGenerator()
    with pytest.raises(ValueError):
        generator.prepare({"domains": []})


def test_email_proof_reuses_precomputed_name_sets(monkeypatch) -> None:
    from ton.generators import identity

    generator = EmailGenerator()
    prepared = generator.prepare({"domains": ["example.com"]})
    monkeypatch.setattr(identity, "GIVEN_NAMES", ())
    monkeypatch.setattr(identity, "FAMILY_NAMES", ())

    assert generator.prove(prepared, TransformResult("alex.adams@example.com")).ok


def test_phone_format_replaces_only_hash() -> None:
    gen = PhoneGenerator()
    prepared = gen.prepare({"format": "+1 (###) ###-####"})
    value = gen.generate(prepared, Random(0))
    assert re.fullmatch(r"\+1 \(\d{3}\) \d{3}-\d{4}", value)
    assert prepared.segments == ("+1 (", "", "", ") ", "", "", "-", "", "", "", "")


def test_phone_requires_at_least_one_hash() -> None:
    generator = PhoneGenerator()
    with pytest.raises(ValueError):
        generator.prepare({"format": "no-digits"})

"""Tests for the bytes generator."""

from __future__ import annotations

import base64
import re
from random import Random

import pytest

from ton.generators.bytes import BytesGenerator


def test_default_hex_encoding_length() -> None:
    gen = BytesGenerator()
    prepared = gen.prepare({"length": 16})
    value = gen.generate(prepared, Random(0))
    assert re.fullmatch(r"[0-9a-f]{32}", value)


def test_base64_encoding_round_trip() -> None:
    gen = BytesGenerator()
    prepared = gen.prepare({"length": 32, "encoding": "base64"})
    value = gen.generate(prepared, Random(0))
    assert len(base64.b64decode(value)) == 32


def test_base32_encoding_round_trip() -> None:
    gen = BytesGenerator()
    prepared = gen.prepare({"length": 20, "encoding": "base32"})
    value = gen.generate(prepared, Random(0))
    assert len(base64.b32decode(value)) == 20


def test_seed_determinism() -> None:
    gen = BytesGenerator()
    prepared = gen.prepare({"length": 8, "encoding": "hex"})
    assert gen.generate(prepared, Random(42)) == gen.generate(prepared, Random(42))


def test_rejects_zero_length() -> None:
    with pytest.raises(ValueError):
        BytesGenerator().prepare({"length": 0})


def test_rejects_unknown_encoding() -> None:
    with pytest.raises(ValueError):
        BytesGenerator().prepare({"encoding": "rot13"})

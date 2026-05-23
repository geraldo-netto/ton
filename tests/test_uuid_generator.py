"""Tests for the uuid generator."""

from __future__ import annotations

import re
import uuid
from random import Random

import pytest

from ton.generators.uuid import UUIDGenerator

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def test_uuid4_default_format_and_version() -> None:
    gen = UUIDGenerator()
    prepared = gen.prepare({})
    value = gen.generate(prepared, Random(0))
    assert _UUID_RE.match(value)
    assert uuid.UUID(value).version == 4


def test_uuid4_is_seed_deterministic() -> None:
    gen = UUIDGenerator()
    prepared = gen.prepare({"version": 4})
    assert gen.generate(prepared, Random(42)) == gen.generate(prepared, Random(42))


def test_uuid_uppercase_flag() -> None:
    gen = UUIDGenerator()
    prepared = gen.prepare({"version": 4, "uppercase": True})
    value = gen.generate(prepared, Random(0))
    assert value == value.upper()


def test_uuid1_supported_but_not_seeded() -> None:
    gen = UUIDGenerator()
    prepared = gen.prepare({"version": 1})
    value = gen.generate(prepared, Random(0))
    assert uuid.UUID(value).version == 1


def test_uuid_rejects_unsupported_version() -> None:
    with pytest.raises(ValueError):
        UUIDGenerator().prepare({"version": 7})

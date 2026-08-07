"""Tests for the uuid generator."""

from __future__ import annotations

import re
import uuid
from random import Random

import pytest

from ton.generators.uuid import UUIDGenerator

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def test_uuid4_default_format_and_version() -> None:
    gen = UUIDGenerator()
    prepared = gen.prepare({})
    value = gen.generate(prepared, Random(0))
    assert _UUID_RE.match(value)
    assert uuid.UUID(value).version == 4


def test_uuid4_is_seed_deterministic() -> None:
    gen = UUIDGenerator()
    prepared = gen.prepare({"version": 4})
    first = gen.generate(prepared, Random(42))
    second = gen.generate(prepared, Random(42))
    assert first == second


def test_uuid_uppercase_flag() -> None:
    gen = UUIDGenerator()
    prepared = gen.prepare({"version": 4, "uppercase": True})
    value = gen.generate(prepared, Random(0))
    assert value == value.upper()


def test_uuid1_is_synthetic_and_seed_deterministic() -> None:
    # v1 is now built from the seeded RNG (DG-003): reproducible and free
    # of the host MAC/clock.
    gen = UUIDGenerator()
    prepared = gen.prepare({"version": 1})
    value = gen.generate(prepared, Random(0))
    assert uuid.UUID(value).version == 1
    first = gen.generate(prepared, Random(7))
    second = gen.generate(prepared, Random(7))
    assert first == second


def test_uuid_rejects_unsupported_version() -> None:
    generator = UUIDGenerator()
    with pytest.raises(ValueError):
        generator.prepare({"version": 7})

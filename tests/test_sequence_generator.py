"""Tests for the sequence generator."""

from __future__ import annotations

from random import Random

import pytest

from ton import api
from ton._transforms import TransformResult
from ton.generators.sequence import SequenceGenerator


def test_sequence_starts_at_zero_by_default() -> None:
    gen = SequenceGenerator()
    prepared = gen.prepare({})
    assert [gen.generate(prepared, Random()) for _ in range(3)] == ["0", "1", "2"]


def test_sequence_honors_start_and_step() -> None:
    gen = SequenceGenerator()
    prepared = gen.prepare({"start": 100, "step": 5})
    assert [gen.generate(prepared, Random()) for _ in range(3)] == ["100", "105", "110"]


def test_sequence_pads_with_zeros() -> None:
    gen = SequenceGenerator()
    prepared = gen.prepare({"start": 1, "padWidth": 4})
    assert gen.generate(prepared, Random()) == "0001"


def test_sequence_rejects_zero_step() -> None:
    generator = SequenceGenerator()
    with pytest.raises(ValueError):
        generator.prepare({"step": 0})


def test_sequence_rejects_negative_pad_width() -> None:
    generator = SequenceGenerator()
    with pytest.raises(ValueError, match="padWidth.*>= 0"):
        generator.prepare({"padWidth": -1})


def test_sequence_through_engine() -> None:
    config = {
        "rows": 5,
        "format": "row=$id$",
        "types": {"id": {"type": "sequence", "start": 10}},
    }
    rows = list(api.generate(config))
    assert rows == ["row=10", "row=11", "row=12", "row=13", "row=14"]


@pytest.mark.parametrize(
    ("value", "expected"), [("10", True), ("14", True), ("11", False), ("-999", False)]
)
def test_sequence_proof_checks_configured_progression(value: str, expected: bool) -> None:
    generator = SequenceGenerator()
    prepared = generator.prepare({"start": 10, "step": 2})

    assert generator.prove(prepared, TransformResult(value)).ok is expected


def test_sequence_proof_checks_descending_progression_and_padding() -> None:
    generator = SequenceGenerator()
    prepared = generator.prepare({"start": 5, "step": -2, "padWidth": 3})

    assert generator.prove(prepared, TransformResult("005")).ok
    assert generator.prove(prepared, TransformResult("-01")).ok
    assert not generator.prove(prepared, TransformResult("002")).ok
    assert not generator.prove(prepared, TransformResult("5")).ok

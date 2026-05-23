"""Tests for the weighted generator."""

from __future__ import annotations

from collections import Counter
from random import Random

import pytest

from ton.generators.weighted import WeightedGenerator


def test_weighted_parallel_arrays_distribution() -> None:
    gen = WeightedGenerator()
    prepared = gen.prepare({"values": ["A", "B"], "weights": [9, 1]})
    rng = Random(0)
    counts = Counter(gen.generate(prepared, rng) for _ in range(2000))
    # 90/10 split; allow generous slack.
    assert counts["A"] > counts["B"] * 4


def test_weighted_record_form() -> None:
    gen = WeightedGenerator()
    prepared = gen.prepare({
        "values": [{"value": "x", "weight": 1}, {"value": "y", "weight": 0}],
    })
    rng = Random(0)
    assert all(gen.generate(prepared, rng) == "x" for _ in range(50))


def test_weighted_rejects_empty_values() -> None:
    with pytest.raises(ValueError):
        WeightedGenerator().prepare({"values": [], "weights": []})


def test_weighted_rejects_mismatched_weights() -> None:
    with pytest.raises(ValueError):
        WeightedGenerator().prepare({"values": ["A", "B"], "weights": [1]})


def test_weighted_rejects_negative_weight() -> None:
    with pytest.raises(ValueError):
        WeightedGenerator().prepare({"values": ["A"], "weights": [-1]})


def test_weighted_rejects_zero_total() -> None:
    with pytest.raises(ValueError):
        WeightedGenerator().prepare({"values": ["A", "B"], "weights": [0, 0]})
